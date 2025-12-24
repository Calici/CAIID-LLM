cmake_minimum_required(VERSION 3.28)

project (drug_search)

option (
    DRUG_SEARCH_USE_SYSTEM_SPECIFIC_CALL
    "Use system specific system calls"
    ON
)
option (
    DRUG_SEARCH_CROSS_COMPILE_WSL "Cross Compile for WSL" OFF
)
set (DRUG_SEARCH_EXECUTABLE_NAME "Drug Search")
# add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/libs/jowi-generic)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/libs/jowi-cli)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/libs/jowi-process)

add_executable(main ${CMAKE_CURRENT_LIST_DIR}/main.cc)
target_link_libraries(main
    PRIVATE
        jowi::cli
        jowi::process
        jowi::crogger
)
target_compile_definitions(main
    PRIVATE
        EXECUTABLE_NAME="${DRUG_SEARCH_EXECUTABLE_NAME}"
        FRONTEND_CONTAINER_NAME="drug-search-chat-frontend"
        BACKEND_CONTAINER_NAME="drug-search-chat-backend"
        DEFAULT_DATA_DIR="data"
        DEFAULT_MODEL_PATH="llms/gemma-3-12B-it-Q4.gguf"
        DEFAULT_BACKEND_PATH="chat-backend.tar.gz"
        DEFAULT_FRONTEND_PATH="chat-frontend.tar.gz"
)

if (DRUG_SEARCH_CROSS_COMPILE_WSL)
    target_compile_definitions(main
        PRIVATE
            DEFAULT_LLAMA_PATH="llama.cpp/llama-server.exe"
    )
else()
    target_compile_definitions(main
        PRIVATE
            DEFAULT_LLAMA_PATH="llama.cpp/llama-server"
    )
endif()

set_target_properties(main PROPERTIES OUTPUT_NAME "Drug Search")
