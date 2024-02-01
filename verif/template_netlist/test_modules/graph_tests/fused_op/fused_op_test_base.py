# SPDX-FileCopyrightText: © 2024 Tenstorrent AI ULC

# SPDX-License-Identifier: Apache-2.0
from test_modules.common.data_formats import DataFormat
from test_modules.common.device_architecture import *
from test_modules.common.enums import TMS, Untilize
from test_modules.common.node import Node, NodeType
from test_modules.graph_tests.graph_test_base import GraphTestBase
from z3 import Implies

import random

class FusedOpTestBase(GraphTestBase):
    """Base class for all fused op graph tests. Encapsulates all common constraints."""

    def additional_constraints(self) -> None:
        """Add solver constraints relevant for all fused ops."""
        # The following constraints come from the current fused op limitations and issues.
        # The full list can be found in src/net2hlks/README.md.

        for op in self.ops:
            if op.type == NodeType.FusedOp:
                # Fused ops cannot be untilized, so we need to force untilize_output attribute to false.
                output_queue: Node = self.get_output_queues()[0]
                output_op: Node = self.nodes[output_queue.input]
                self.solver.add(output_op.untilize == Untilize.false.value)

        for scheduled_op in output_op.scheduled_ops:
            for input_id, input_name in enumerate(scheduled_op.inputs):
                input_tms_attr_name = self.op_input_tms_format.format(input_id)
                tm_config = getattr(scheduled_op, input_tms_attr_name, [])
                input_node = self.nodes[input_name]

                for tm in tm_config:
                    # Broadcasted dimension needs to be 1.
                    if tm.tm_type == TMS.c_broadcast.value:
                        self.solver.add(input_node.mb_n == 1)
                        self.solver.add(input_node.ub_c == 1)
                    elif tm.tm_type == TMS.r_broadcast.value:
                        self.solver.add(input_node.mb_m == 1)
                        self.solver.add(input_node.ub_r == 1)
                        # mb column needs to be 1 when broadcast increases mb row.
                        self.solver.add(Implies(scheduled_op.mb_m != 1, input_node.mb_n == 1))

                # We don't support reblocking.
                # Matmul and reduce are already handled in the base class.
                if (
                    scheduled_op.type != NodeType.ScheduledMatmulOp
                    and scheduled_op.type != NodeType.ScheduledReduceOp
                ):
                    r_changed = False
                    c_changed = False

                    for tm in tm_config:
                        if tm.tm_type == TMS.r_broadcast.value:
                            r_changed = True
                        elif tm.tm_type == TMS.c_broadcast.value:
                            c_changed = True

                    if not r_changed:
                        self.solver.add(scheduled_op.mb_m == input_node.mb_m)
                        self.solver.add(scheduled_op.ub_r == input_node.ub_r)

                    if not c_changed:
                        self.solver.add(scheduled_op.mb_n == input_node.mb_n)
                        self.solver.add(scheduled_op.ub_c == input_node.ub_c)

    # @override
    def constrain_data_format(self) -> None:
        """Constraints data formats for all nodes in the graph.
        In addition to constraints generated by TemplateNetlistTestBase
        here we try to randomize data formats on all input queues and all
        intermediate, accumulation and output data formats for all ops and all scheduled ops.
        Since currently fused ops have limitation that all data formats need be
        eighter A or B (eg: Bfp8_b vs Bfp8) we need to constrain all formats to one
        side or the other (Only exception to this rule is Float32 which can be used
        with both A and B formats.)
        """
        # true a exp type inputs, false b exp type inputs
        a_or_b_inputs = random.choice([True, False])

        valid_values_a = [DataFormat.Bfp8.value, DataFormat.Float16.value, DataFormat.Float32.value]
        valid_values_b = [
            DataFormat.Bfp8_b.value,
            DataFormat.Float16_b.value,
            DataFormat.Float32.value,
        ]

        # Check if any op or any scheduled op is of type reciprocal
        any_op_is_reciprocal = False
        any_op_is_reduce = False
        for op_node in self.ops:
            if op_node.op_type == "reciprocal":
                any_op_is_reciprocal = True
            elif op_node.type == NodeType.ReduceOp:
                any_op_is_reduce = True
            elif op_node.type == NodeType.FusedOp:
                if op_node.has_reciprocal_scheduled_op:
                    any_op_is_reciprocal = True
                if op_node.has_reduce_scheduled_op:
                    any_op_is_reduce = True

        # Pick output data format
        valid_output_formats_a = [DataFormat.Float16.value, DataFormat.Float32.value]
        valid_output_formats_b = [DataFormat.Float16_b.value, DataFormat.Float32.value]
        if not any_op_is_reciprocal:
            valid_output_formats_a.append(DataFormat.Bfp8.value)
            valid_output_formats_b.append(DataFormat.Bfp8_b.value)

        # Configure data formats on input queues
        for q_node in self.get_input_queues():
            input_df = random.choice(valid_values_a if a_or_b_inputs else valid_values_b)
            self.solver.add(q_node.df == input_df)

        output_queue = self.get_output_queues()[0]
        output_op = self.nodes[output_queue.input]

        for op_node in self.ops:
            # Set accumulation data format; a inputs cannot be used with reduce op using dest acc Float32
            # tenstorrent/budabackend#1464
            if self.arch.supports_float32_accumulation and not (any_op_is_reduce and a_or_b_inputs):
                accumulation_data_format = (
                    random.choice([DataFormat.Float32.value, DataFormat.Float16.value])
                    if a_or_b_inputs
                    else random.choice([DataFormat.Float32.value, DataFormat.Float16_b.value])
                )
            else:
                accumulation_data_format = (
                    DataFormat.Float16.value if a_or_b_inputs else DataFormat.Float16_b.value
                )

            self.solver.add(op_node.acc_df == accumulation_data_format)

            # Set intermed data format.
            intermed_df = (
                random.choice(valid_output_formats_a) if a_or_b_inputs else random.choice(valid_output_formats_b)
            )
            self.solver.add(op_node.intermed_df == intermed_df)

            # Set op output df
            if op_node == output_op and self.arch.supports_float32_accumulation:
                # On Wormhole_b0 output df doesn't have to follow A/B rules
                # to make things simpler for test generation, we only flip A/B side on
                # output of the last op in the graph to have some test coverage.
                output_df = (
                    random.choice(valid_output_formats_b) if a_or_b_inputs else random.choice(valid_output_formats_a)
                )
            else:
                output_df = (
                    random.choice(valid_output_formats_a) if a_or_b_inputs else random.choice(valid_output_formats_b)
                )
            self.solver.add(op_node.out_df == output_df)

        # Configure output queue to have same df as output df of the last op in the graph
        self.solver.add(output_op.out_df == output_queue.df)

        # Set dummy format for "self.data_format" just to make TemplateNetlistTestBase happy
        self.solver.add(self.data_format == DataFormat.Float16.value)