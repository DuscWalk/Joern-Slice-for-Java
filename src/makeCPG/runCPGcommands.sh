#!/bin/bash

# 依次执行每一行命令
while IFS= read -r cmd; do
    echo "正在执行: $cmd"
    eval "$cmd"
done < "CPGcommands.txt"