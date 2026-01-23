# Talos Gateway Service - Claude Integration Guide

**Repo Role**: High-availability FastAPI-based ingress/egress point for the Talos Network, serving as the primary API gateway and WebSocket interface.

## Component Overview

The Talos Gateway is a critical infrastructure component that bridges standard HTTPS/WebSocket clients with the P2P Talos Network. It provides:

- REST API endpoints for audit events and integrity verification
- WebSocket connections for real-time streaming
- MCP (Multi-Client Protocol) routing and proxying
- Rate limiting and security controls
- Prometheus metrics collection
- Health and readiness monitoring

## Key Features

### API Endpoints

#### Core Audit Event APIs
- `POST /api/events` - Create new audit events with integrity hashing
- `GET /api/events` - List recent audit events with filtering capabilities
- `GET /api/events/stats` - Retrieve audit statistics for time windows

#### MCP Integration APIs
- `GET /v1/mcp/servers` - List available MCP servers
- `GET /v1/mcp/servers/{server_id}/tools` - List tools for a specific server
- `GET /v1/mcp/servers/{server_id}/tools/{tool_name}/schema` - Get schema for a specific tool
- `POST /v1/mcp/servers/{server_id}/tools/{tool_name}:call` - Invoke a tool through proxy

#### Admin APIs
- `GET /admin/v1/me` - Get current user profile
- `GET /admin/v1/secrets` - List secret keys (metadata only)
- `GET /admin/v1/telemetry/stats` - Get telemetry statistics
- `GET /admin/v1/audit/stats` - Get audit event statistics

#### Health and Monitoring
- `GET /healthz` - Liveness probe
- `GET /readyz` - Readiness probe with dependency checks
- `GET /version` - Version information
- `GET /metrics` - Prometheus metrics endpoint
- `GET /api/gateway/status` - Gateway status for integration tests

### WebSocket Support

The gateway implements real-time WebSocket streaming through:
- Session management for persistent connections
- Event broadcasting to connected clients
- Stream handlers for bidirectional communication

### Security Features

- CORS middleware for controlled cross-origin requests
- Capability verification for tool access control
- Session-based authentication (development mode)
- Rate limiting per IP and per key
- Audit logging for all gateway operations

## Technical Architecture

### Framework Stack
- **FastAPI**: High-performance Python web framework
- **Uvicorn**: ASGI server for asynchronous operations
- **Pydantic**: Data validation and serialization
- **Requests**: HTTP client for upstream service calls
- **Prometheus Client**: Metrics collection and exposure

### Core Components

1. **Main Application (`main.py`)**
   - FastAPI application setup and configuration
   - Router registration (MCP, admin, WebSocket)
   - Middleware configuration (CORS, Prometheus)
   - Health and monitoring endpoints
   - Audit event processing and storage

2. **Routers**
   - `mcp.py`: MCP server integration and tool proxying
   - `admin.py`: Administrative endpoints with auth requirements
   - `stream.py`: WebSocket connection handling

3. **Handlers**
   - Stream handlers for WebSocket session management
   - Event broadcasting utilities

4. **Models**
   - Pydantic models for request/response validation
   - Audit event schemas and integrity structures

### Data Flow

1. **Incoming Requests**
   - HTTP requests routed through FastAPI endpoints
   - Authentication and capability verification
   - Request processing and business logic execution
   - Database operations through SDK ports
   - Response generation with integrity hashes

2. **WebSocket Streaming**
   - Persistent connections managed by session handlers
   - Real-time event broadcasting to clients
   - Bidirectional communication support

3. **MCP Integration**
   - Server registry lookup for upstream services
   - JSON-RPC proxying to MCP connectors
   - Tool schema retrieval and validation
   - Capability-based access control

## Dependencies

### Python Packages
- `fastapi>=0.100.0`: Web framework
- `uvicorn>=0.20.0`: ASGI server
- `pydantic>=2.0.0`: Data validation
- `requests>=2.31.0`: HTTP client
- `psycopg2-binary>=2.9.0`: PostgreSQL adapter
- `python-dotenv>=1.0.0`: Environment variable loading
- `prometheus-client>=0.19.0`: Metrics collection

### Internal Dependencies
- `talos-sdk-py`: Core SDK for audit storage and hashing
- `talos-contracts`: Canonical contract implementations

## Deployment

### Docker Configuration
- Multi-stage build process (builder and runtime stages)
- Non-root user execution for security
- Health checks for container orchestration
- Environment variable configuration
- Port exposure on 8080

### Environment Variables
- `GIT_SHA`: Git commit hash for build identification
- `VERSION`: Application version
- `BUILD_TIME`: Build timestamp
- `DEV_MODE`: Development mode flag
- `MCP_GIT_URL`: Git MCP server URL
- `MCP_WEATHER_URL`: Weather MCP server URL

## Integration Points

### Upstream Services
- **MCP Connectors**: Various microservices implementing specific tools
- **Audit Storage**: PostgreSQL database for audit event persistence
- **Identity Service**: Authentication and authorization provider (future)

### Downstream Clients
- **Web Dashboard**: Administration and monitoring interface
- **SDK Clients**: Third-party integrations using REST APIs
- **WebSocket Clients**: Real-time event subscribers

## Monitoring and Observability

### Metrics Collection
- Request counters by method, endpoint, and status
- Latency histograms for performance tracking
- Capability verification counters
- Active session gauges

### Health Checks
- Liveness probe (`/healthz`): Basic application health
- Readiness probe (`/readyz`): Dependency availability verification
- Version endpoint (`/version`): Build and deployment information

## Development Workflow

### Quickstart
```bash
./scripts/start.sh
```

### Testing
```bash
make test
./scripts/test.sh
```

### Common Operations
1. **Connect Client**: POST to `/api/v1/message`
2. **Invoke Tool**: POST to `/v1/mcp/servers/{server_id}/tools/{tool_name}:call`
3. **Monitor Events**: WebSocket connection to streaming endpoint

## Security Considerations

### Threat Model
- Public-facing ingress point requiring robust security controls
- Authentication and authorization enforcement points
- Data integrity and audit trail requirements

### Security Guarantees
- Rate limiting per IP and per key
- Capability-based access control for tool operations
- Session management for persistent connections
- Audit logging for all gateway interactions
- CORS policy enforcement

## Future Enhancements

### Planned Improvements
- Enhanced authentication with JWT validation
- Improved secret management integration
- Advanced rate limiting algorithms
- Distributed tracing implementation
- Enhanced error handling and recovery

## References

1. [Talos Wiki](https://github.com/talosprotocol/talos/wiki)
2. [Architecture Documentation](https://github.com/talosprotocol/talos/wiki/Architecture)
3. [FastAPI Documentation](https://fastapi.tiangolo.com/)
4. [Prometheus Client Documentation](https://github.com/prometheus/client_python)

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).