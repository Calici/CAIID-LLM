#!/bin/bash
# Assume that we are currently in a MacOs environment
rm -rf export
rm -rf chat-executable/*-build
cd chat-executable

# CREATE FOLDER
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk \
CC=/opt/homebrew/opt/llvm/bin/clang \
CXX=/opt/homebrew/opt/llvm/bin/clang++ \
cmake \
-Bmacos-arm64-build -GNinja \
-DCMAKE_OSX_ARCHITECTURES=arm64 \
-DCMAKE_BUILD_TYPE=Release .
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk \
CC=/opt/homebrew/opt/llvm/bin/clang \
CXX=/opt/homebrew/opt/llvm/bin/clang++ \
cmake \
-Bmacos-x86-build -GNinja \
-DCMAKE_OSX_ARCHITECTURES=x86_64 \
-DCMAKE_BUILD_TYPE=Release .
docker run \
    -it \
    --rm \
    -v ./:/app \
    -w /app \
    --env CXX=clang++ \
    --env CC=clang \
    --platform linux/amd64 \
    jowillianto/cpp-module-toolchain:jammy-cmake3.31-ninja1.11-llvm20 \
    cmake \
    -DCMAKE_EXE_LINKER_FLAGS=-lc++abi \
    -DCMAKE_CXX_FLAGS="-stdlib=libc++ -static" \
    -DCMAKE_BUILD_TYPE=Release \
    -GNinja \
    -Blinux-x86-build \
    .
docker run \
    -it \
    --rm \
    -v ./:/app \
    -w /app \
    --env CXX=clang++ \
    --env CC=clang \
    --platform linux/amd64 \
    jowillianto/cpp-module-toolchain:jammy-cmake3.31-ninja1.11-llvm20 \
    cmake \
    -DCMAKE_EXE_LINKER_FLAGS=-lc++abi \
    -DCMAKE_CXX_FLAGS="-stdlib=libc++ -static" \
    -DCMAKE_BUILD_TYPE=Release \
    -DDRUG_SEARCH_CROSS_COMPILE_WSL=ON \
    -GNinja \
    -Bwin-wsl-build \
    .

## COMPILE
cd macos-arm64-build && ninja && cd ..
cd macos-x86-build && ninja && cd ..
docker run \
    -it \
    --rm \
    -v ./:/app \
    -w /app/linux-x86-build \
    --env CXX=clang++ \
    --env CC=clang \
    --platform linux/amd64 \
    jowillianto/cpp-module-toolchain:jammy-cmake3.31-ninja1.11-llvm20 \
    ninja
docker run \
    -it \
    --rm \
    -v ./:/app \
    -w /app/win-wsl-build \
    --env CXX=clang++ \
    --env CC=clang \
    --platform linux/amd64 \
    jowillianto/cpp-module-toolchain:jammy-cmake3.31-ninja1.11-llvm20 \
    ninja


# Copy Exec
cd ..
mkdir export \
    export/linux \
    export/macos_arm64 \
    export/macos_x86 \
    export/windows \
    export/linux/llama.cpp \
    export/macos_arm64/llama.cpp \
    export/macos_x86/llama.cpp \
    export/windows/llama.cpp \
    export/linux/llms \
    export/macos_arm64/llms \
    export/macos_x86/llms \
    export/windows/llms \

cp chat-executable/macos-arm64-build/Drug\ Search export/macos_arm64
cp chat-executable/macos-x86-build/Drug\ Search export/macos_x86
cp chat-executable/linux-x86-build/Drug\ Search export/linux
cp chat-executable/win-wsl-build/Drug\ Search export/windows

# Copy llama
cp precompiled/linux/llama-server export/linux/llama.cpp
cp precompiled/windows/llama-server.exe export/windows/llama.cpp
cp precompiled/macos/llama-server export/macos_arm64/llama.cpp
cp precompiled/macos/llama-server export/macos_x86/llama.cpp

# push docker container out
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t drug-search-chat-frontend \
    --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 \
    chat-frontend
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t drug-search-chat-backend \
    chat-backend

# WRITE TAR
docker image save \
    --platform linux/amd64 \
    -o export/linux/chat-frontend.tar.gz \
    drug-search-chat-frontend
docker image save \
    --platform linux/amd64 \
    -o export/linux/chat-backend.tar.gz \
    drug-search-chat-backend
cp export/linux/*.tar.gz export/windows/
cp export/linux/*.tar.gz export/macos_x86
docker image save \
    --platform linux/arm64 \
    -o export/macos_arm64/chat-frontend.tar.gz \
    drug-search-chat-frontend
docker image save \
    --platform linux/arm64 \
    -o export/macos_arm64/chat-backend.tar.gz \
    drug-search-chat-backend

# All Done, delete
rm -r chat-executable/macos-arm64-build
rm -r chat-executable/macos-x86-build
rm -r chat-executable/win-wsl-build
rm -r chat-executable/linux-x86-build

# Put models
scp cal-tb01:/developer/jowi/llm-models/gemma-3-12B-it-Q4.gguf export/linux/llms/
cp export/linux/llms/* export/macos_x86/llms
cp export/linux/llms/* export/windows/llms
cp export/linux/llms/* export/macos_arm64/llms

# Now tar or zip
cd export
zip -vr linux.zip linux
zip -vr macos_arm64.zip macos_arm64
zip -vr macos_x86.zip macos_x86
zip -vr windows.zip windows

cp *.zip /Volumes/NO\ NAME