#include <algorithm>
#include <atomic>
#include <csignal>
#include <cstdlib>
#include <expected>
#include <filesystem>
#include <format>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <utility>
import jowi.cli;
import jowi.process;
import jowi.crogger;

namespace cli = jowi::cli;
namespace proc = jowi::process;
namespace fs = std::filesystem;
namespace log = jowi::crogger;

struct FileCloser {
  void operator()(std::FILE *f) {
    if (f != nullptr) {
      std::fclose(f);
    }
  }
};

std::unique_ptr<std::FILE, FileCloser> null_file{std::fopen("/dev/null", "w")};

struct AppState {
  std::optional<fs::path> data_dir;
  std::optional<fs::path> llama_model_path;
  std::optional<fs::path> llama_path;
  std::atomic_flag interrupted;
  int llama_port = 8080;
  size_t llama_context_size = 0;
  size_t llama_gpu_layers = 100;

  fs::path resolved_model_path() const {
    return llama_model_path.value_or(DEFAULT_MODEL_PATH);
  }

  fs::path resolved_data_path() const {
    auto p = fs::absolute(data_dir.value_or(DEFAULT_DATA_DIR));
    if (!fs::is_directory(p)) {
      fs::create_directories(p);
    }
    return fs::canonical(p);
  }
  fs::path backend_path() const {
    return DEFAULT_BACKEND_PATH;
  }
  fs::path resolved_llama_path() const {
    return llama_path.value_or(DEFAULT_LLAMA_PATH);
  }
};

cli::AppIdentity app_id{
  "Drug Search",
  "Command Line Interface to Launch the Drug Searcher",
  "Calici Ltd.",
  "Proprietary Software Licensed to Receivers",
  cli::AppVersion{0, 0, 0}
};

static AppState state;

void on_keyboard_interrupt(int sig) {
  if (sig == SIGINT) {
    state.interrupted.test_and_set(std::memory_order_release);
    log::info(log::Message{"CTRL+C caught, terminating program"});
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
    auto start = std::chrono::steady_clock::now();
    std::vector<bool> is_dead(procs.size(), false);
    size_t try_count = 1;
    while (std::chrono::steady_clock::now() - start < std::chrono::seconds{10}) {
      log::info(log::Message{"Terminating Programs: Try {} / 11", try_count});
      for (size_t i = 0; i != procs.size(); i += 1) {
        if (!is_dead[i]) {
          auto res = procs[i].wait_non_blocking();
          if ((res && res->has_value()) || !res) {
            is_dead[i] = true;
          }
        }
      }
      try_count += 1;
      if (std::ranges::all_of(is_dead, [](bool x) { return x; })) break;
      std::this_thread::sleep_for(std::chrono::seconds{1});
    }
    for (size_t i = 0; i != procs.size(); i += 1) {
      if (!is_dead[i]) {
        procs[i].kill_and_wait();
      }
    }
    log::info(log::Message{"Terminated All Programs"});
    procs.clear();
  }
  ~ProcessManager() {
    if (!procs.empty()) {
      terminate();
    }
  }
};

std::expected<ProcessManager, proc::SubprocessError> run_stack(const AppState &state, bool heavy) {
  ProcessManager procs;
  log::info(log::Message{"Spawning chat-backend"});
  auto backend_proc = proc::spawn(
    {"docker",
     "run",
     "--rm",
     "-v",
     std::format("{}:{}", state.resolved_data_path().string(), "/data"),
     "-p",
     "8000:8000",
     "drug-search-chat-backend"},
    0,
    fileno(null_file.get()),
    2
  );
  if (!backend_proc) {
    log::error(log::Message{"Fail to spawn chat-backend"});
    return std::unexpected{backend_proc.error()};
  }
  procs.emplace_back(std::move(backend_proc).value());
  log::info(log::Message{"Spawning chat-frontend"});
  auto frontend_proc = proc::spawn(
    {"docker", "run", "--rm", "-p", "3000:3000", "drug-search-chat-frontend"},
    0,
    fileno(null_file.get()),
    2
  );
  if (!frontend_proc) {
    log::error(log::Message{"Fail to spawn chat-frontend"});
    return std::unexpected{frontend_proc.error()};
  }
  procs.emplace_back(std::move(frontend_proc).value());
  if (heavy) {
    log::info(log::Message{"Spawning llama-cpp"});
    auto llama_proc = proc::spawn(
      {
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
      },
      0,
      fileno(null_file.get()),
      2
    );
    if (!llama_proc) {
      log::error(log::Message{"Fail to spawn llama.cpp"});
      return std::unexpected{llama_proc.error()};
    }
    procs.emplace_back(std::move(llama_proc).value());
  }
  log::info(log::Message{"Spawned chat-backend"});
  log::info(log::Message{"Spawned chat-frontend"});
  if (heavy) log::info(log::Message{"Spawned llama-cpp"});
  return std::expected<ProcessManager, proc::SubprocessError>{std::move(procs)};
}

std::expected<void, proc::SubprocessError> condition_load_image(
  std::string_view img_name, const fs::path &load_path, bool force
) {
  return proc::run(
           {"docker", "image", "inspect", img_name},
           false,
           fileno(null_file.get()),
           std::nullopt,
           fileno(null_file.get())
  )
    .transform([](auto res) { return res.exit_code() == 0; })
    .and_then([&](bool exist) {
      if (exist && !force) return std::expected<void, proc::SubprocessError>{};
      return proc::run({"docker", "image", "load", "-i", load_path.c_str()}).transform([](auto) {});
    });
}

std::expected<void, proc::SubprocessError> build_containers(const AppState &state, bool update) {
  return condition_load_image(FRONTEND_CONTAINER_NAME, DEFAULT_FRONTEND_PATH, update)
    .and_then([&]() {
      return condition_load_image(BACKEND_CONTAINER_NAME, DEFAULT_BACKEND_PATH, update);
    });
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
        "The amount of layers to offload to GPU. To offload all, just put a big number. Default: 100"
      )
      .require_value()
      .optional();
    app.add_argument("--context_size")
      .help("The amount of context size for the model. Default: Max Amount")
      .require_value()
      .optional();
    // Additional Argument if not using apple MacOs
    app.parse_args();
    state.llama_path = app.args().first_of("--llama").transform(cli::parse_arg<fs::path>);
    state.llama_model_path = app.args().first_of("--model").transform(cli::parse_arg<fs::path>);
    state.llama_port =
      app.expect(app.args().first_of("--port").transform(cli::parse_arg<int>).value_or(8080));
    state.llama_gpu_layers = app.expect(
      app.args().first_of("--offload_layers").transform(cli::parse_arg<int>).value_or(100)
    );
    state.llama_context_size =
      app.expect(app.args().first_of("--context_size").transform(cli::parse_arg<int>).value_or(0));
    auto procs = cli::App::expect(run_stack(state, true));
    state.interrupted.wait(false, std::memory_order_acquire);
  }
};

struct LiteAction {
  void operator()(cli::App &app) {
    auto procs = app.expect(run_stack(state, false));
    state.interrupted.wait(false, std::memory_order_acquire);
  }
};

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
  state.data_dir = app.args().first_of("--data").transform(cli::parse_arg<fs::path>);
  log::info(log::Message{"Data Directory:  {}", state.resolved_data_path().c_str()});
  log::info(
    log::Message{
      "Loading Application Container: {}",
      app.args().contains("--update") ? "Force Update" : "Check and No Update"
    }
  );
  cli::App::expect(build_containers(state, app.args().contains("--update")));
  cli::ActionBuilder{app, "The mode to run the model for"}
    .add_action(
      "heavy", "Runs the Heavy Mode by also running a local llama.cpp server", HeavyAction{}
    )
    .add_action("lite", "Use an OpenAI API Key with the platform", LiteAction{})
    .run();
}
