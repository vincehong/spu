// Copyright 2026 The SPU Authors. All Rights Reserved.
// Licensed under the Apache License, Version 2.0 (the "License");
// https://www.apache.org/licenses/LICENSE-2.0
//
// FactoryMem (one process, three threads) or FactoryBrpc (three processes)
// SPDZwise RING vs ABY3 kernel benches used for the localhost RTT sweep.

#include <array>
#include <chrono>
#include <type_traits>
#include <condition_variable>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>

#include "yacl/link/factory.h"

#include "libspu/mpc/ab_api.h"
#include "libspu/mpc/aby3/io.h"
#include "libspu/mpc/aby3/protocol.h"
#include "libspu/mpc/aby3/type.h"
#include "libspu/mpc/api.h"
#include "libspu/mpc/spdzwise/io.h"
#include "libspu/mpc/spdzwise/protocol.h"
#include "libspu/mpc/spdzwise/ring_type.h"
#include "libspu/mpc/spdzwise/state.h"
#include "libspu/mpc/utils/simulate.h"

namespace spu::mpc::spdzwise {
namespace {
using Clock = std::chrono::steady_clock;

struct Options {
  std::string protocol = "spdzwise";
  std::string op = "trunc";
  std::string transport = "mem";
  std::string parties = "127.0.0.1:61540,127.0.0.1:61541,127.0.0.1:61542";
  int rank = 0;
  int64_t count = 4096;
  int reps = 3;
  int64_t rows = 256;
  int64_t cols = 64;
};

double Ms(Clock::time_point a, Clock::time_point b = Clock::now()) {
  return std::chrono::duration<double, std::milli>(b - a).count();
}

class Barrier {
  std::mutex mutex_;
  std::condition_variable cv_;
  size_t arrived_ = 0, generation_ = 0;

 public:
  void wait() {
    std::unique_lock<std::mutex> lock(mutex_);
    const auto generation = generation_;
    if (++arrived_ == 3) {
      arrived_ = 0;
      ++generation_;
      cv_.notify_all();
    } else {
      cv_.wait(lock, [&] { return generation_ != generation; });
    }
  }
};

uint64_t SplitMix(uint64_t& state) {
  uint64_t z = (state += 0x9e3779b97f4a7c15ULL);
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
  return z ^ (z >> 31);
}

bool IsWise(const std::string& protocol) { return protocol == "spdzwise"; }

NdArrayRef VectorInput(int64_t count, uint64_t seed) {
  NdArrayRef out(makeType<RingTy>(FM64), {count});
  for (int64_t i = 0; i < count; ++i) {
    out.data<uint64_t>()[i] = SplitMix(seed) & ((uint64_t(1) << 48) - 1);
  }
  return out;
}

NdArrayRef MatrixInput(int64_t rows, int64_t cols, uint64_t seed) {
  NdArrayRef out(makeType<RingTy>(FM64), {rows, cols});
  for (int64_t i = 0; i < out.numel(); ++i) {
    out.data<uint64_t>()[i] = SplitMix(seed) & ((uint64_t(1) << 24) - 1);
  }
  return out;
}

void SendBytes(const std::shared_ptr<yacl::link::Context>& link, size_t dst,
               const NdArrayRef& array, const std::string& tag) {
  const auto compact = array.isCompact() ? array : array.clone();
  const auto nbytes = compact.numel() * static_cast<int64_t>(compact.elsize());
  link->Send(dst, yacl::ByteContainerView(compact.data<std::byte>(), nbytes),
             tag);
}

NdArrayRef RecvBytes(const std::shared_ptr<yacl::link::Context>& link,
                     size_t src, const Type& type, const Shape& shape,
                     const std::string& tag) {
  auto buf = link->Recv(src, tag);
  const auto nbytes = shape.numel() * static_cast<int64_t>(type.size());
  SPU_ENFORCE(buf.size() == nbytes, "share size mismatch: got {} want {}",
              buf.size(), nbytes);
  auto owned = std::make_shared<yacl::Buffer>(nbytes);
  std::memcpy(owned->data(), buf.data(), static_cast<size_t>(nbytes));
  return NdArrayRef(owned, type, shape);
}

void Sync(const std::shared_ptr<yacl::link::Context>& link,
          const std::string& tag) {
  const char token = 'x';
  link->Send(link->NextRank(), yacl::ByteContainerView(&token, 1), tag);
  auto got = link->Recv(link->PrevRank(), tag);
  SPU_ENFORCE(got.size() == 1);
}

std::vector<std::string> SplitParties(const std::string& parties) {
  std::vector<std::string> hosts;
  std::string cur;
  for (char c : parties) {
    if (c == ',') {
      if (!cur.empty()) {
        hosts.push_back(cur);
        cur.clear();
      }
    } else if (c != ' ') {
      cur.push_back(c);
    }
  }
  if (!cur.empty()) {
    hosts.push_back(cur);
  }
  return hosts;
}

std::shared_ptr<yacl::link::Context> ConnectBrpc(const Options& opt) {
  yacl::link::ContextDesc desc;
  desc.id = "spdzwise-rtt-sweep";
  desc.recv_timeout_ms = 30 * 60 * 1000;
  const auto hosts = SplitParties(opt.parties);
  SPU_ENFORCE(hosts.size() == 3, "need three host:port parties, got {}",
              opt.parties);
  for (size_t i = 0; i < hosts.size(); ++i) {
    desc.parties.push_back({fmt::format("party{}", i), hosts[i]});
  }
  auto ctx = yacl::link::FactoryBrpc().CreateContext(desc, opt.rank);
  ctx->ConnectToMesh();
  return ctx;
}

RuntimeConfig MakeConfig(const std::string& protocol) {
  RuntimeConfig config(IsWise(protocol) ? SPDZWISE : ABY3, FM64);
  config.spdzwise_config.domain = SpdzWiseConfig::RING;
  config.spdzwise_config.check_threshold = 5'000'000;
  config.fxp_fraction_bits = 18;
  config.experimental_enable_inter_op_par = false;
  config.experimental_enable_intra_op_par = false;
  return config;
}

Type InputType(const std::string& protocol, size_t rank, bool boolean) {
  if (IsWise(protocol)) {
    return boolean ? makeType<BInputTy>(rank, 64)
                   : makeType<ring::InputTy>(rank);
  }
  if (boolean) {
    return makeType<aby3::BShrTy>(PT_U64, 64);
  }
  return makeType<aby3::AShrTy>(FM64);
}

struct PartyIn {
  std::vector<NdArrayRef> shares;
};

struct PartyOut {
  double total_ms = 0;
  size_t sent_bytes = 0;
  size_t sent_actions = 0;
  NdArrayRef output;
};

Value TruncExactOrNative(SPUContext* ctx, const Value& x,
                         const std::string& protocol) {
  if (protocol == "aby3-exact") {
    return b2a(ctx, arshift_b(ctx, a2b(ctx, x), {16}));
  }
  return trunc_a(ctx, x, 16, SignType::Unknown);
}

PartyOut RunParty(const std::shared_ptr<yacl::link::Context>& link,
                  const Options& opt, const PartyIn& input, Barrier* barrier) {
  const bool wise = IsWise(opt.protocol);
  auto config = MakeConfig(opt.protocol);
  std::unique_ptr<SPUContext> ctx =
      wise ? std::make_unique<SPUContext>(config, link)
           : makeAby3Protocol(config, link);
  if (wise) {
    registerArithmeticPrototype(ctx.get(), link);
  }
  auto* state = wise ? ctx->prot()->getState<SpdzWiseState>() : nullptr;
  ProtocolRunGuard guard(ctx.get());

  std::vector<Value> values;
  std::vector<std::string> names;
  for (size_t i = 0; i < input.shares.size(); ++i) {
    names.push_back(fmt::format("in{}", i));
    DataType dtype = (opt.op == "b2a") ? DT_U64 : DT_I64;
    if (opt.op == "a2b" || opt.op == "b2a") {
      dtype = DT_U64;
    }
    values.emplace_back(input.shares[i], dtype);
  }

  if (wise) {
    state->begin(ExecutableProto(opt.op + "-bench", names, {"y"}, "test"),
                 values);
    for (auto& value : values) {
      value = import_s(ctx.get(), value);
    }
    state->verify();
  }

  const auto stats = link->GetStats();
  if (barrier) {
    barrier->wait();
  } else {
    Sync(link, "start-" + opt.op);
  }
  const auto bytes0 = stats->sent_bytes.load();
  const auto actions0 = stats->sent_actions.load();
  const auto start = Clock::now();

  Value y;
  if (opt.op == "trunc") {
    y = TruncExactOrNative(ctx.get(), values[0], opt.protocol);
  } else if (opt.op == "a2b") {
    y = a2b(ctx.get(), values[0]);
  } else if (opt.op == "b2a") {
    y = b2a(ctx.get(), values[0]);
  } else if (opt.op == "mmul") {
    y = mmul_aa(ctx.get(), values[0], values[1]);
  } else if (opt.op == "linear") {
    y = TruncExactOrNative(ctx.get(), mmul_aa(ctx.get(), values[0], values[1]),
                           opt.protocol);
  } else {
    SPU_THROW("unknown op {}", opt.op);
  }

  if (wise) {
    state->prepareOutputs(ctx.get(), {"y"}, {y});
    guard.commit();
  } else {
    guard.commit();
  }
  const auto stop = Clock::now();

  PartyOut out;
  out.total_ms = Ms(start, stop);
  out.sent_bytes = stats->sent_bytes.load() - bytes0;
  out.sent_actions = stats->sent_actions.load() - actions0;
  out.output = wise ? state->exportedValue("y").data() : y.data();
  return out;
}

std::vector<NdArrayRef> MakeShares(const Options& opt, const NdArrayRef& plain,
                                   bool boolean) {
  SpdzWiseIo wise_io(FM64, 3, SpdzWiseConfig::RING);
  auto aby_io = aby3::makeAby3Io(FM64, 3);
  if (boolean) {
    auto shares = wise_io.toBooleanShares(plain, 64);
    if (!IsWise(opt.protocol)) {
      for (auto& share : shares) {
        share = share.as(makeType<aby3::BShrTy>(PT_U64, 64));
      }
    }
    return shares;
  }
  return IsWise(opt.protocol) ? wise_io.toShares(plain, VIS_SECRET)
                              : aby_io->toShares(plain, VIS_SECRET, -1);
}

NdArrayRef Reconstruct(const Options& opt,
                       const std::vector<NdArrayRef>& shares) {
  SpdzWiseIo wise_io(FM64, 3, SpdzWiseConfig::RING);
  auto aby_io = aby3::makeAby3Io(FM64, 3);
  return IsWise(opt.protocol) ? wise_io.fromShares(shares)
                              : aby_io->fromShares(shares);
}

struct Workload {
  std::vector<NdArrayRef> plains;
  std::vector<bool> boolean;
};

Workload BuildWorkload(const Options& opt) {
  Workload work;
  if (opt.op == "mmul" || opt.op == "linear") {
    work.plains.push_back(
        MatrixInput(opt.rows, opt.cols, 0x4d4d554c414141ULL));
    work.plains.push_back(MatrixInput(opt.cols, 1, 0x574549474854ULL));
    work.boolean = {false, false};
  } else if (opt.op == "b2a") {
    work.plains.push_back(VectorInput(opt.count, 0x42324153454544ULL));
    work.boolean = {true};
  } else {
    work.plains.push_back(VectorInput(opt.count, 0x5452554e4331ULL));
    work.boolean = {false};
  }
  return work;
}

void PrintHeader() {
  std::cout << std::fixed << std::setprecision(6)
            << "protocol,op,transport,rank,iteration,count,rows,cols,total_ms,"
               "sent_bytes,sent_actions\n";
}

void PrintRow(const Options& opt, int iteration, const PartyOut& r) {
  std::cout << opt.protocol << ',' << opt.op << ',' << opt.transport << ','
            << (opt.transport == "mem" ? 0 : opt.rank) << ',' << iteration
            << ',' << opt.count << ',' << opt.rows << ',' << opt.cols << ','
            << r.total_ms << ',' << r.sent_bytes << ',' << r.sent_actions
            << '\n';
}

std::vector<PartyIn> ShareAll(const Options& opt, const Workload& work) {
  std::vector<PartyIn> parties(3);
  for (size_t i = 0; i < work.plains.size(); ++i) {
    auto shares = MakeShares(opt, work.plains[i], work.boolean[i]);
    for (size_t rank = 0; rank < 3; ++rank) {
      parties[rank].shares.push_back(shares[rank]);
    }
  }
  return parties;
}

void RunMem(const Options& opt) {
  PrintHeader();
  const auto work = BuildWorkload(opt);
  for (int iteration = 0; iteration <= opt.reps; ++iteration) {
    auto parties = ShareAll(opt, work);
    Barrier barrier;
    const auto results = utils::simulate(
        3, [&](const std::shared_ptr<yacl::link::Context>& link) {
          return RunParty(link, opt, parties[link->Rank()], &barrier);
        });
    double wall = 0;
    size_t bytes = 0, actions = 0;
    std::vector<NdArrayRef> outputs;
    for (size_t rank = 0; rank < 3; ++rank) {
      wall = std::max(wall, results[rank].total_ms);
      bytes += results[rank].sent_bytes;
      actions += results[rank].sent_actions;
      outputs.push_back(results[rank].output);
    }
    Reconstruct(opt, outputs);
    Options row = opt;
    PartyOut summary;
    summary.total_ms = wall;
    summary.sent_bytes = bytes;
    summary.sent_actions = actions;
    PrintRow(row, iteration, summary);
    std::cout.flush();
    std::cerr << opt.protocol << ' ' << opt.op << " mem iteration " << iteration
              << " wall_ms=" << wall << " sent_bytes=" << bytes << '\n';
  }
}

PartyIn RecvInputs(const Options& opt, const Workload& work,
                   const std::shared_ptr<yacl::link::Context>& link) {
  PartyIn mine;
  if (opt.rank == 0) {
    auto parties = ShareAll(opt, work);
    mine = parties[0];
    for (size_t dst = 1; dst < 3; ++dst) {
      for (size_t i = 0; i < parties[dst].shares.size(); ++i) {
        SendBytes(link, dst, parties[dst].shares[i],
                  fmt::format("in-{}-{}", dst, i));
      }
    }
  } else {
    for (size_t i = 0; i < work.plains.size(); ++i) {
      mine.shares.push_back(RecvBytes(
          link, 0, InputType(opt.protocol, opt.rank, work.boolean[i]),
          work.plains[i].shape(), fmt::format("in-{}-{}", opt.rank, i)));
    }
  }
  return mine;
}

void RunBrpc(const Options& opt) {
  auto link = ConnectBrpc(opt);
  if (opt.rank == 0) {
    PrintHeader();
  }
  const auto work = BuildWorkload(opt);
  for (int iteration = 0; iteration <= opt.reps; ++iteration) {
    auto mine = RecvInputs(opt, work, link);
    auto result = RunParty(link, opt, mine, nullptr);
    if (opt.rank == 0) {
      std::vector<NdArrayRef> outputs(3);
      outputs[0] = result.output;
      for (size_t src = 1; src < 3; ++src) {
        Type ty = result.output.eltype();
        if (ty.isa<ring::OutputTy>()) {
          ty = makeType<ring::OutputTy>(
              src, ty.as<ring::OutputTy>()->binding());
        } else if (ty.isa<BOutputTy>()) {
          ty = makeType<BOutputTy>(src, ty.as<BShare>()->nbits(),
                                   ty.as<BOutputTy>()->binding());
        }
        outputs[src] = RecvBytes(link, src, ty, result.output.shape(),
                                 fmt::format("out-{}", src));
      }
      Reconstruct(opt, outputs);
    } else {
      SendBytes(link, 0, result.output, fmt::format("out-{}", opt.rank));
    }
    const auto packed = std::array<uint64_t, 3>{
        static_cast<uint64_t>(result.total_ms * 1000.0), result.sent_bytes,
        result.sent_actions};
    if (opt.rank == 0) {
      double wall = result.total_ms;
      size_t bytes = result.sent_bytes;
      size_t actions = result.sent_actions;
      for (int src = 1; src < 3; ++src) {
        auto buf = link->Recv(src, fmt::format("stat-{}", src));
        SPU_ENFORCE(buf.size() == static_cast<int64_t>(sizeof(packed)));
        std::array<uint64_t, 3> sample{};
        std::memcpy(sample.data(), buf.data(), sizeof(sample));
        wall = std::max(wall, sample[0] / 1000.0);
        bytes += sample[1];
        actions += sample[2];
      }
      PartyOut summary;
      summary.total_ms = wall;
      summary.sent_bytes = bytes;
      summary.sent_actions = actions;
      PrintRow(opt, iteration, summary);
      std::cout.flush();
      std::cerr << opt.protocol << ' ' << opt.op << " brpc iteration "
                << iteration << " wall_ms=" << wall << " sent_bytes=" << bytes
                << '\n';
    } else {
      link->Send(0, yacl::ByteContainerView(packed.data(), sizeof(packed)),
                 fmt::format("stat-{}", opt.rank));
    }
  }
}

Options Parse(int argc, char** argv) {
  Options opt;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    auto take = [&](const char* key, std::string* dst) {
      const std::string prefix = std::string(key) + "=";
      if (a.rfind(prefix, 0) == 0) {
        *dst = a.substr(prefix.size());
        return true;
      }
      return false;
    };
    auto take_i = [&](const char* key, auto* dst) {
      std::string s;
      if (!take(key, &s)) {
        return false;
      }
      *dst = static_cast<std::remove_cv_t<std::remove_reference_t<decltype(*dst)>>>(
          std::stoll(s));
      return true;
    };
    if (take("--protocol", &opt.protocol) || take("--op", &opt.op) ||
        take("--transport", &opt.transport) ||
        take("--parties", &opt.parties) || take_i("--rank", &opt.rank) ||
        take_i("--count", &opt.count) || take_i("--reps", &opt.reps) ||
        take_i("--rows", &opt.rows) || take_i("--cols", &opt.cols)) {
      continue;
    }
    SPU_THROW("unknown argument {}", a);
  }
  SPU_ENFORCE(opt.protocol == "spdzwise" || opt.protocol == "aby3" ||
              opt.protocol == "aby3-exact");
  SPU_ENFORCE(opt.op == "trunc" || opt.op == "a2b" || opt.op == "b2a" ||
              opt.op == "mmul" || opt.op == "linear");
  SPU_ENFORCE(opt.transport == "mem" || opt.transport == "brpc");
  SPU_ENFORCE(opt.count > 0 && opt.reps > 0 && opt.rows > 0 && opt.cols > 0);
  SPU_ENFORCE(opt.rank >= 0 && opt.rank < 3);
  if (opt.op == "trunc" && opt.protocol == "aby3") {
    // Native ABY3 TruncAPr2 remains available under protocol=aby3.
  }
  return opt;
}

}  // namespace
}  // namespace spu::mpc::spdzwise

int main(int argc, char** argv) {
  try {
    const auto opt = spu::mpc::spdzwise::Parse(argc, argv);
    if (opt.transport == "mem") {
      spu::mpc::spdzwise::RunMem(opt);
    } else {
      spu::mpc::spdzwise::RunBrpc(opt);
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
