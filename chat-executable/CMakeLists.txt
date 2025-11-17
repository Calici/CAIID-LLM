cmake_minimum_required(VERSION 3.28)

project (drug_search)

option (
    DRUG_SEARCH_USE_SYSTEM_SPECIFIC_CALL
    "Use system specific system calls"
    ON
)
set (DRUG_SEARCH_EXECUTABLE_NAME "Drug Search")
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/libs/jowi-generic)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/libs/jowi-process)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/libs/jowi-cli)

add_executable(main ${CMAKE_CURRENT_LIST_DIR}/main.cc)
target_link_libraries(main
    PRIVATE
        jowi::cli
        jowi::crogger
        jowi::process
)
target_compile_definitions(main
    PRIVATE
        EXECUTABLE_NAME="${DRUG_SEARCH_EXECUTABLE_NAME}"
        FRONTEND_CONTAINER_NAME="drug-search-chat-frontend"
        BACKEND_CONTAINER_NAME="drug-search-chat-backend"
)
if (WIN32)
    target_compile_definitions(main
        PRIVATE
            PLATFORM="WINDOWS"
            DEFAULT_LLAMA_PATH="llama.cpp/llama-server"
            DEFAULT_MODEL_PATH="llms/gemma-3-12B-it-Q4.gguf"
            DEFAULT_BACKEND_PATH="chat-backend"
            DEFAULT_FRONTEND_PATH="chat-frontend"
    )
elseif (APPLE)
    target_compile_definitions(main
        PRIVATE
            PLATFORM="APPLE"
            DEFAULT_DATA_DIR="/Library/Preferences/${DRUG_SEARCH_EXECUTABLE_NAME}/data"
            DEFAULT_LLAMA_PATH="llama.cpp/llama-server"
            DEFAULT_MODEL_PATH="llms/gemma-3-12B-it-Q4.gguf"
            DEFAULT_BACKEND_PATH="chat-backend"
            DEFAULT_FRONTEND_PATH="chat-frontend"
    )
elseif (UNIX)
    target_compile_definitions(main
        PRIVATE
            PLATFORM="UNIX"
            DEFAULT_DATA_DIR="data"
            DEFAULT_LLAMA_PATH="llama.cpp/llama-server"
            DEFAULT_MODEL_PATH="llms/gemma-3-12B-it-Q4.gguf"
            DEFAULT_BACKEND_PATH="chat-backend"
            DEFAULT_FRONTEND_PATH="chat-frontend"
    )
endif()

set_target_properties(main PROPERTIES OUTPUT_NAME "Drug Search")
