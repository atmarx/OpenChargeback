#!/bin/bash
# OpenChargeback Service Management Script
# Usage: scripts/service.sh [--start|--stop|--restart|--watch|--status|--logs] [--env dev|prod]
# Run from project root directory

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENV="dev"
ACTION=""
COMPOSE_FILE="docker/docker-compose.yml"
PROJECT_NAME="openchargeback"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --start)
            ACTION="start"
            shift
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --restart)
            ACTION="restart"
            shift
            ;;
        --watch)
            ACTION="watch"
            shift
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --logs)
            ACTION="logs"
            shift
            ;;
        --build)
            ACTION="build"
            shift
            ;;
        --env)
            ENV="$2"
            shift 2
            ;;
        -h|--help)
            echo "OpenChargeback Service Management"
            echo ""
            echo "Usage: $0 [action] [options]"
            echo ""
            echo "Actions:"
            echo "  --start     Start the service"
            echo "  --stop      Stop the service"
            echo "  --restart   Restart the service"
            echo "  --watch     Start with live reload (dev only)"
            echo "  --status    Show service status"
            echo "  --logs      Show service logs"
            echo "  --build     Build/rebuild the Docker image"
            echo ""
            echo "Options:"
            echo "  --env       Environment: dev (default) or prod"
            echo "  -h, --help  Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --start                    # Start in dev mode"
            echo "  $0 --start --env prod         # Start in production mode"
            echo "  $0 --watch                    # Start with live reload"
            echo "  $0 --logs                     # View logs"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate action
if [[ -z "$ACTION" ]]; then
    echo -e "${RED}Error: No action specified${NC}"
    echo "Use --help for usage information"
    exit 1
fi

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo -e "${RED}Error: Invalid environment '$ENV'. Use 'dev' or 'prod'${NC}"
    exit 1
fi

# Set environment-specific variables
if [[ "$ENV" == "prod" ]]; then
    export COMPOSE_PROFILES="production"
    DOCKER_OPTS="-d"
else
    export COMPOSE_PROFILES="development"
    DOCKER_OPTS=""
fi

echo -e "${BLUE}OpenChargeback Service Manager${NC}"
echo -e "Environment: ${GREEN}$ENV${NC}"
echo ""

# Helper function for docker compose
dc() {
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

# Check if docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo -e "${RED}Error: Docker is not running${NC}"
        exit 1
    fi
}

# Actions
case $ACTION in
    start)
        check_docker
        echo -e "${GREEN}Starting OpenChargeback...${NC}"

        if [[ "$ENV" == "dev" ]]; then
            # In dev mode, use local Python with reload and instance directory
            if [[ ! -f "instance/config.yaml" ]]; then
                echo -e "${YELLOW}Warning: instance/config.yaml not found. Copying from config.example.yaml${NC}"
                mkdir -p instance
                cp config.example.yaml instance/config.yaml
            fi

            echo -e "${BLUE}Starting local development server...${NC}"
            source .venv/bin/activate 2>/dev/null || {
                echo -e "${YELLOW}Creating virtual environment...${NC}"
                python -m venv .venv
                source .venv/bin/activate
                pip install -e .
            }
            openchargeback serve --reload --config instance/config.yaml --host 0.0.0.0
        else
            # In prod mode, use Docker
            dc up $DOCKER_OPTS --build
        fi
        ;;

    stop)
        check_docker
        echo -e "${YELLOW}Stopping OpenChargeback...${NC}"
        dc down
        echo -e "${GREEN}Service stopped${NC}"
        ;;

    restart)
        check_docker
        echo -e "${YELLOW}Restarting OpenChargeback...${NC}"
        dc down
        dc up $DOCKER_OPTS --build
        echo -e "${GREEN}Service restarted${NC}"
        ;;

    watch)
        echo -e "${GREEN}Starting OpenChargeback in watch mode...${NC}"

        if [[ ! -f "instance/config.yaml" ]]; then
            echo -e "${YELLOW}Warning: instance/config.yaml not found. Copying from config.example.yaml${NC}"
            mkdir -p instance
            cp config.example.yaml instance/config.yaml
        fi

        # Use local Python with reload for watch mode
        source .venv/bin/activate 2>/dev/null || {
            echo -e "${YELLOW}Creating virtual environment...${NC}"
            python -m venv .venv
            source .venv/bin/activate
            pip install -e .
        }

        echo -e "${BLUE}Starting with auto-reload enabled...${NC}"
        echo -e "${GREEN}Open http://127.0.0.1:8000 in your browser${NC}"
        echo ""
        openchargeback serve --reload --config instance/config.yaml --host 0.0.0.0
        ;;

    status)
        check_docker
        echo -e "${BLUE}Service Status:${NC}"
        dc ps
        ;;

    logs)
        check_docker
        echo -e "${BLUE}Service Logs:${NC}"
        dc logs -f --tail=100
        ;;

    build)
        check_docker
        echo -e "${BLUE}Building Docker image...${NC}"
        dc build
        echo -e "${GREEN}Build complete${NC}"
        ;;

    *)
        echo -e "${RED}Unknown action: $ACTION${NC}"
        exit 1
        ;;
esac
