#include <atomic>
#include <chrono>
#include <concepts>
#include <csignal>
#include <cstdlib>
#include <exception>
#include <expected>
#include <filesystem>
#include <format>
#include <functional>
#include <initializer_list>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
import jowi.cli;
import jowi.crogger;
import jowi.process;

namespace cli = jowi::cli;
namespace proc = jowi::process;
namespace fs = std::filesystem;

struct AppState {
  fs::path app_dir;
  std::optional<fs::path> data_dir;
  std::optional<fs::path> llama_model_path;
  std::optional<fs::path> llama_path;
  std::atomic_flag interrupted;
  int llama_port = 8080;
  size_t llama_context_size = 0;
  size_t llama_gpu_layers = 100;

  AppState(fs::path app) : app_dir{std::move(app)} {}

  fs::path resolved_model_path() const {
    return llama_model_path.value_or(app_dir / DEFAULT_MODEL_PATH);
  }

  fs::path resolved_data_path() const {
    return data_dir.value_or(DEFAULT_DATA_DIR);
  }
  fs::path backend_path() const {
    return app_dir / DEFAULT_BACKEND_PATH;
  }
  fs::path resolved_llama_path() const {
    return llama_path.value_or(app_dir / DEFAULT_LLAMA_PATH);
  }
};

cli::AppIdentity app_id{
  "Drug Search",
  "Command Line Interface to Launch the Drug Searcher",
  "Calici Ltd.",
  "Proprietary Software Licensed to Receivers",
  cli::AppVersion{0, 0, 0}
};

std::optional<AppState> state;

void on_keyboard_interrupt(int sig) {
  if (sig == SIGINT && state) {
    state->interrupted.test_and_set(std::memory_order_release);
  }
}

struct ProcessManager {
  std::vector<proc::Subprocess> procs;

  ProcessManager() : procs{} {}
  ProcessManager(ProcessManager &&p) : procs{std::move(p.procs)} {}
  ProcessManager(const ProcessManager &) = delete;
  ProcessManager &operator=(const ProcessManager &) = delete;
  ProcessManager &operator=(ProcessManager &&p) {
    terminate();
    procs = std::move(p.procs);
    return *this;
  }
  void emplace_back(proc::Subprocess proc) {
    procs.emplace_back(std::move(proc));
  }
  void terminate() {
    for (auto &proc : procs) {
      proc.send_signal(SIGTERM);
    }
    for (auto &proc : procs) {
      proc.wait_or_kill(std::chrono::seconds{10}, false);
    }
    procs.clear();
  }
  ~ProcessManager() {
    terminate();
  }
};

std::expected<ProcessManager, proc::SubprocessError> run_stack(const AppState &state, bool heavy) {
  ProcessManager procs;
  auto backend_proc = proc::spawn(
    {"docker",
     "run",
     "--rm",
     "-v",
     std::format("{}:{}", state.resolved_data_path().string(), "/data"),
     "-p",
     "8000:8000",
     "drug-search-chat-backend"}
  );
  if (!backend_proc) {
    return std::unexpected{backend_proc.error()};
  }
  procs.emplace_back(std::move(backend_proc).value());
  auto frontend_proc =
    proc::spawn({"docker", "run", "--rm", "-p", "3000:3000", "drug-search-chat-frontend"});
  if (!backend_proc) {
    return std::unexpected{frontend_proc.error()};
  }
  procs.emplace_back(std::move(frontend_proc).value());
  if (heavy) {
    auto llama_proc = proc::spawn({
      state.resolved_llama_path().string(),
      "--host",
      "0.0.0.0",
      "--port",
      std::to_string(state.llama_port),
      "-m",
      state.resolved_model_path().string(),
      "--no-webui",
      "--context-shift",
      "--ctx_size",
      std::to_string(state.llama_context_size),
      "--jinja",
      "-ngl",
      std::to_string(state.llama_gpu_layers),
    });
    if (!llama_proc) {
      return std::unexpected{llama_proc.error()};
    }
    procs.emplace_back(std::move(llama_proc).value());
  }
  return std::expected<ProcessManager, proc::SubprocessError>{std::move(procs)};
}

struct HeavyAction {
  void operator()(cli::App &app) {
    app.add_argument("--llama")
      .help("The path to the llama executable. Default: In App")
      .require_value()
      .optional();
    app.add_argument("--model")
      .help("The Path to the GGUF LLM Model to use. Default: In App")
      .require_value()
      .optional();
    app.add_argument("--port")
      .help("The port to run llama server from. Default: 8080")
      .require_value()
      .optional();
    app.add_argument("--offload_layers")
      .help(
        "The amount of layers to offload to GPU. To offload all, just put a big number. Default: All"
      )
      .require_value()
      .optional();
    app.add_argument("--context_size")
      .help("The amount of context size for the model. Default: Max Amount")
      .require_value()
      .optional();
    // Additional Argument if not using apple MacOs
    app.parse_args();
    state->llama_path = app.args().first_of("--llama").transform(cli::parse_arg<fs::path>);
    state->llama_model_path = app.args().first_of("--model").transform(cli::parse_arg<fs::path>);
    state->llama_port =
      app.expect(app.args().first_of("--port").transform(cli::parse_arg<int>).value_or(8080));
    state->llama_gpu_layers = app.expect(
      app.args().first_of("--offload_layers").transform(cli::parse_arg<int>).value_or(100)
    );
    state->llama_context_size =
      app.expect(app.args().first_of("--context_size").transform(cli::parse_arg<int>).value_or(0));
    auto procs = app.expect(run_stack(state.value(), true));
    state->interrupted.wait(false, std::memory_order_acquire);
  }
};

struct LiteAction {
  void operator()(cli::App &app) {
    auto procs = app.expect(run_stack(state.value(), false));
    state->interrupted.wait(false, std::memory_order_acquire);
  }
};

std::expected<bool, proc::SubprocessError> check_image(std::string_view name) {
  return proc::run({"docker", "image", "inspect", name}, false).transform([](auto res) {
    return res.exit_code() == 0;
  });
}

std::expected<void, proc::SubprocessError> build_containers(const AppState &state, bool update) {
  return proc::run({"docker",
                    "build",
                    "-f",
                    state.app_dir / DEFAULT_FRONTEND_PATH / "dockerfile",
                    "--build-arg",
                    "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000",
                    state.app_dir / DEFAULT_FRONTEND_PATH})
    .transform([&](auto) {})
    .and_then([&]() {
      return proc::run({"docker",
                        "build",
                        "-f",
                        state.app_dir / DEFAULT_BACKEND_PATH / "dockerfile",
                        state.app_dir / DEFAULT_BACKEND_PATH})
        .transform([&](auto) {});
    });
}

int main(int argc, const char **argv, const char **envp) {
  proc::SubprocessEnv::init(envp);
  signal(SIGINT, on_keyboard_interrupt);
  cli::App app{app_id, argc, argv, envp};
  app.add_argument("--data")
    .help("The path to the data folder. This should store user data")
    .require_value()
    .optional();
  app.add_argument("--update")
    .help("If the docker containers should be rebuild on startup")
    .as_flag();
  app.parse_args(false);
  auto app_dir = fs::current_path();
  state.emplace(app_dir);
  state->data_dir = app.args().first_of("--data").transform(cli::parse_arg<fs::path>);
  app.expect(build_containers(state.value(), true));
  cli::ActionBuilder{app, "The mode to run the model for"}
    .add_action(
      "heavy", "Runs the Heavy Mode by also running a local llama.cpp server", HeavyAction{}
    )
    .add_action("lite", "Use an OpenAI API Key with the platform", LiteAction{})
    .run();
}
