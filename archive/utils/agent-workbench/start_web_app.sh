#!/usr/bin/env bash

echo "Starting MS Discovery agent workbench..."
echo

# Ensure the script runs from its own directory so relative paths resolve correctly
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Clean transient session folder quietly if present
[ -d "user-session" ] && rm -rf "user-session"

# --- Ensure Python is installed and recent enough
echo "Checking for Python installation..."

# Check if we have a Python virtual environment
if [ -d "venv" ]; then
  echo "Found virtual environment (venv/)"
  PY_VENV="venv"
elif [ -d ".venv" ]; then
  echo "Found virtual environment (.venv/)"
  PY_VENV=".venv"
else
  # Fallback: try to create with python3 if available, otherwise python
  if command -v python3 >/dev/null 2>&1; then
    PY=python3
    echo "Creating virtual environment with system Python 3..."
  elif command -v python >/dev/null 2>&1; then
    PY=python
    echo "Creating virtual environment with system Python..."
  else
    echo "ERROR: Python is not installed or not on PATH."
    echo "Install Python 3.9+ (macOS: brew install python3; Ubuntu: sudo apt-get install python3 python3-venv)"
    exit 1
  fi

  # Verify Python version is sufficient (>= 3.9)
  if ! "$PY" - <<'PYVER'
import sys
v=sys.version_info
sys.exit(0 if (v.major>3 or (v.major==3 and v.minor>=9)) else 1)
PYVER
  then
    echo "ERROR: Python 3.9 or newer is required. Detected: $("$PY" --version 2>&1)"
    exit 1
  fi

  # Create virtual environment
  echo "Creating virtual environment..."
  "$PY" -m venv venv || { echo "Failed to create virtualenv"; exit 1; }
  PY_VENV="venv"
fi

# Activate virtual environment
echo "Activating virtual environment..."
# shellcheck disable=SC1091
source "$PY_VENV/bin/activate"

# Upgrade pip first
echo "Upgrading pip..."
python -m pip install --upgrade pip

# Clean install of dependencies
echo "Cleaning old dependencies..."
pip uninstall -y openai httpx || true

echo "Installing dependencies (prefer binary wheels)..."
if pip install -q --prefer-binary -r requirements.txt >/dev/null 2>&1; then
  :
elif pip install -q --only-binary=:all: -r requirements.txt >/dev/null 2>&1; then
  :
else
  echo "Binary-only install failed. Retrying normal install to allow source builds (may require compilers/Rust)..."
  if ! pip install -q -r requirements.txt >/dev/null 2>&1; then
    echo "ERROR: All install attempts failed. See pip output above for details."
    exit 1
  fi
fi

echo
echo "Installing Discovery CLI (Python package)..."
if ! command -v git >/dev/null 2>&1; then
  echo
  echo "WARNING: 'git' is not installed. Skipping Discovery CLI installation."
  echo "Some features may be unavailable. Install Git (https://git-scm.com/downloads) to enable Discovery CLI."
  echo "Continuing to start the web UI without Discovery CLI..."
  echo
elif ! python -m pip install --upgrade "git+https://github.com/microsoft/discovery.git#subdirectory=utils/supercomputer-cli/discovery" 2>&1; then
  echo
  echo "WARNING: Failed to install the Discovery CLI Python package."
  echo "This may be due to authentication issues or network problems."
  echo "Some features may be unavailable. Continuing to start the web UI without Discovery CLI..."
  echo
fi

echo "Loading environment configuration..."
echo "Web application environment ready!"

# Check if Docker is installed and running
echo "Checking Docker installation..."

# Function to check if Docker is installed
check_docker_installed() {
  command -v docker >/dev/null 2>&1
}

# Function to check if Docker daemon is running
check_docker_running() {
  docker version >/dev/null 2>&1
}

# Function to install Docker on macOS
install_docker_mac() {
  echo
  echo "🐳 Docker is not installed. Choose installation method:"
  echo
  echo "1. Docker Desktop (Recommended - Official, includes GUI, BuildKit/buildx)"
  echo "   • Full-featured Docker environment"
  echo "   • Easy to use with GUI controls"
  echo "   • ~500MB download, requires license for large companies"
  echo
  echo "2. Colima (Lightweight - Open source, CLI-only)"
  echo "   • Minimal resource usage"
  echo "   • Fast and lightweight"
  echo "   • Free for all uses"
  echo
  echo "Enter choice (1 or 2), or anything else to skip: "
  read -r -t 30 choice || choice="skip"

  case "$choice" in
    1)
      echo
      echo "Installing Docker Desktop..."
      echo "This will download Docker Desktop and install it via Homebrew Cask."
      echo

      # Check if Homebrew is installed
      if ! command -v brew >/dev/null 2>&1; then
        echo "❌ ERROR: Homebrew is not installed."
        echo "Please install Homebrew first: https://brew.sh"
        echo "Or download Docker Desktop manually: https://www.docker.com/products/docker-desktop/"
        return 1
      fi

      if brew install --cask docker; then
        echo
        echo "✅ Docker Desktop installed successfully"
        echo
        echo "📱 Please complete the setup:"
        echo "   1. Open Docker Desktop from Applications"
        echo "   2. Accept the service agreement"
        echo "   3. Wait for Docker to start (whale icon in menu bar)"
        echo "   4. Then re-run this script: ./start_web_app.sh"
        echo
        echo "Opening Docker Desktop now..."
        open -a Docker
        echo
        echo "Waiting 10 seconds for Docker to initialize..."
        sleep 10

        # Check if Docker is running
        if docker version >/dev/null 2>&1; then
          echo "✅ Docker Desktop is running"
          return 0
        else
          echo "⚠️ Docker Desktop installed but needs manual startup"
          echo "Please start Docker Desktop and re-run this script"
          return 1
        fi
      else
        echo "❌ Failed to install Docker Desktop via Homebrew"
        echo "Download manually: https://www.docker.com/products/docker-desktop/"
        return 1
      fi
      ;;

    2)
      echo
      echo "Installing Colima (lightweight Docker runtime) and Docker CLI..."
      echo "This may take a few minutes..."

      # Check if Homebrew is installed
      if ! command -v brew >/dev/null 2>&1; then
        echo "❌ ERROR: Homebrew is not installed."
        echo "Please install Homebrew first: https://brew.sh"
        return 1
      fi

      # Install colima and docker
      if brew install colima docker; then
        echo
        echo "✅ Colima and Docker CLI installed successfully"
        echo
        echo "Starting Colima Docker engine..."

        # Start colima with reasonable defaults
        if colima start --cpu 2 --memory 4 --disk 60; then
          echo "✅ Colima Docker engine started successfully"

          # Wait a moment for Docker socket to be ready
          sleep 3

          # Verify Docker is working
          if docker version >/dev/null 2>&1; then
            echo "✅ Docker is now operational"
            return 0
          else
            echo "⚠️ Docker installed but not responding. You may need to restart your terminal."
            return 1
          fi
        else
          echo "❌ Failed to start Colima"
          echo "Try manually: colima start"
          return 1
        fi
      else
        echo "❌ Failed to install Docker via Homebrew"
        return 1
      fi
      ;;

    *)
      echo "Skipping Docker installation."
      return 1
      ;;
  esac
}

# Check Docker installation status
if ! check_docker_installed; then
  echo
  echo "⚠️ Docker is not installed on this system."
  echo

  # On macOS, offer to auto-install
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if install_docker_mac; then
      DOCKER_AVAILABLE=1
    else
      echo
      echo "⚠️ Docker installation skipped or failed. Some features will be unavailable."
      echo "You can install Docker later and restart this script."
      echo
      echo "Installation options:"
      echo "  • Docker Desktop: brew install --cask docker"
      echo "  • Colima: brew install colima docker && colima start"
      echo
      DOCKER_AVAILABLE=0
    fi
  else
    # Linux or other OS
    echo "Please install Docker:"
    echo "  • Ubuntu/Debian: sudo apt-get install docker.io"
    echo "  • Fedora: sudo dnf install docker"
    echo "  • Other: https://docs.docker.com/engine/install/"
    echo
    DOCKER_AVAILABLE=0
  fi
elif ! check_docker_running; then
  echo
  echo "⚠️ Docker is installed but not running."
  echo

  # Try to detect which Docker runtime is installed
  if command -v colima >/dev/null 2>&1; then
    echo "Detected Colima. Attempting to start..."
    if colima start; then
      echo "✅ Colima started successfully"
      sleep 3
      if check_docker_running; then
        DOCKER_AVAILABLE=1
      else
        echo "⚠️ Colima started but Docker still not responding"
        DOCKER_AVAILABLE=0
      fi
    else
      echo "❌ Failed to start Colima automatically"
      echo "Try manually: colima start"
      DOCKER_AVAILABLE=0
    fi
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Docker Desktop appears to be installed but not running."
    echo "Please start Docker Desktop from Applications or system tray."
    echo
    DOCKER_AVAILABLE=0
  else
    echo "Please start the Docker daemon:"
    echo "  • Linux: sudo systemctl start docker"
    echo "  • macOS: Start Docker Desktop application"
    echo
    DOCKER_AVAILABLE=0
  fi
else
  echo "✅ Docker is installed and running"
  DOCKER_AVAILABLE=1
fi

# Show final Docker status
if [ "${DOCKER_AVAILABLE:-0}" -eq 0 ]; then
  echo
  echo "⚠️ Starting without Docker support"
  echo "Container-related features will be unavailable until Docker is running."
  echo
fi

# If Docker is available and DOCKER_HOST isn't set, try to auto-detect the engine
# endpoint from the current Docker context (useful on Docker Desktop where
# contexts use a per-user socket like unix:///Users/..../.docker/run/docker.sock).
if [ "${DOCKER_AVAILABLE:-0}" -eq 1 ] && [ -z "${DOCKER_HOST:-}" ]; then
  current_ctx=$(docker context show 2>/dev/null || true)
  if [ -n "$current_ctx" ]; then
    # Attempt to read the 'docker' endpoint for the current context. The
    # inspect template below extracts Endpoints.docker.Host if present.
    ctx_host=$(docker context inspect "$current_ctx" --format '{{ (index .Endpoints "docker").Host }}' 2>/dev/null || true)
    if [ -n "$ctx_host" ] && [ "$ctx_host" != "null" ]; then
      export DOCKER_HOST="$ctx_host"
      echo "Auto-set DOCKER_HOST=$DOCKER_HOST (from docker context: $current_ctx)"
    fi
  fi
fi

if [ "${DOCKER_AVAILABLE:-0}" -eq 1 ]; then
  echo "Docker Engine is running"
else
  echo "Running without Docker support"
fi

# Start the web server
echo "Starting web server..."
echo
echo "WEB INTERFACE:"
echo "   http://localhost:8050"
echo
echo "AGENT CONTAINER MANAGEMENT:"
echo "   Use the web interface to switch agents and manage containers"
echo "   OR use: python agent_container.py switch [agent-name]"
echo
echo "AVAILABLE AGENTS:"
python - <<'PY'
from agent_manager import StaticAgentManager
try:
    m = StaticAgentManager('agents-catalog.yaml')
    [print(f'    - {name}') for name in m.agents.keys()]
except Exception as e:
    print(f'    (failed to load catalog: {e})')
PY

echo
echo "Press Ctrl+C to stop the server"
echo

python web_server.py