#!/bin/bash
cat /localhome/rjakovljevic/work/budabackend/verif/graph_tests/netlists/z3/test_datacopy_matmul_multiple_tms_and_reblock_20220818_143343/test_8feb2bce86934952d1b1bf0dd3eda474/netlist_8feb2bce86934952d1b1bf0dd3eda474.yaml
./build/test/verif/graph_tests/test_graph --netlist /localhome/rjakovljevic/work/budabackend/verif/graph_tests/netlists/z3/test_datacopy_matmul_multiple_tms_and_reblock_20220818_143343/test_8feb2bce86934952d1b1bf0dd3eda474/netlist_8feb2bce86934952d1b1bf0dd3eda474.yaml --silicon --timeout 500 > >(tee /localhome/rjakovljevic/work/budabackend/verif/graph_tests/netlists/z3/test_datacopy_matmul_multiple_tms_and_reblock_20220818_143343/test_8feb2bce86934952d1b1bf0dd3eda474/run.log) 2>&1