// Copyright 2023 Ant Group Co., Ltd.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once

#include "libspu/core/array_ref.h"
#include "libspu/core/cexpr.h"
#include "libspu/mpc/kernel.h"
#include "libspu/mpc/spdz2k/state.h"
#include "libspu/mpc/spdz2k/value.h"

namespace spu::mpc::spdz2k {

class CommonTypeB : public Kernel {
 public:
  static constexpr char kBindName[] = "common_type_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  void evaluate(KernelEvalContext* ctx) const override;
};

class CastTypeB : public CastTypeKernel {
 public:
  static constexpr char kBindName[] = "cast_type_b";

  Kind kind() const override { return Kind::Dynamic; }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in,
                const Type& to_type) const override;
};

class B2P : public UnaryKernel {
 public:
  static constexpr char kBindName[] = "b2p";

  Kind kind() const override { return Kind::Dynamic; }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in) const override;
};

class P2B : public UnaryKernel {
 public:
  static constexpr char kBindName[] = "p2b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in) const override;
};

class NotB : public UnaryKernel {
 public:
  static constexpr char kBindName[] = "not_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in) const override;
};

class BitrevB : public BitrevKernel {
 public:
  static constexpr char kBindName[] = "bitrev_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in, size_t start,
                size_t end) const override;
};

class AndBP : public BinaryKernel {
 public:
  static constexpr char kBindName[] = "and_bp";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& lhs,
                const ArrayRef& rhs) const override;
};

class AndBB : public BinaryKernel {
 public:
  static constexpr char kBindName[] = "and_bb";

  ce::CExpr latency() const override {
    // rotate : 1
    return ce::Const(0);
  }

  ce::CExpr comm() const override {
    // rotate : k
    return ce::Const(0);
  }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& lhs,
                const ArrayRef& rhs) const override;
};

class XorBP : public BinaryKernel {
 public:
  static constexpr char kBindName[] = "xor_bp";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& lhs,
                const ArrayRef& rhs) const override;
};

class XorBB : public BinaryKernel {
 public:
  static constexpr char kBindName[] = "xor_bb";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& lhs,
                const ArrayRef& rhs) const override;
};

class LShiftB : public ShiftKernel {
 public:
  static constexpr char kBindName[] = "lshift_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in,
                size_t bits) const override;
};

class RShiftB : public ShiftKernel {
 public:
  static constexpr char kBindName[] = "rshift_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in,
                size_t bits) const override;
};

class ARShiftB : public ShiftKernel {
 public:
  static constexpr char kBindName[] = "arshift_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in,
                size_t bits) const override;
};

class BitIntlB : public BitSplitKernel {
 public:
  static constexpr char kBindName[] = "bitintl_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in,
                size_t stride) const override;
};

class BitDeintlB : public BitSplitKernel {
 public:
  static constexpr char kBindName[] = "bitdeintl_b";

  ce::CExpr latency() const override { return ce::Const(0); }

  ce::CExpr comm() const override { return ce::Const(0); }

  ArrayRef proc(KernelEvalContext* ctx, const ArrayRef& in,
                size_t stride) const override;
};

}  // namespace spu::mpc::spdz2k
