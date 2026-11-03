# Build from the exact LOCAL inspected image; never rebuild compiler/UI/e-ink.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY reviewed-base.json /opt/mcp-reviewed-base.json
COPY base-preimages.json /opt/mcp-base-preimages.json
COPY verify_base.py /opt/mcp-verify-base.py
RUN python3 /opt/mcp-verify-base.py
COPY payload/app/ /app/app/
COPY payload/source/ /opt/velxio-mcp-source/
COPY payload/scripts/ /app/mcp-compact-scripts/
COPY entrypoint.sh /app/mcp-compact-entrypoint.sh
COPY nginx-mcp.conf /etc/nginx/conf.d/mcp-compact.conf
RUN chmod 0755 /app/mcp-compact-entrypoint.sh
# Fail during the offline image build if installed MCP lacks the required API.
RUN PYTHONPATH=/app python3 -c "from types import SimpleNamespace; from app.mcp.compact.facade import create_facade; create_facade(SimpleNamespace())"
ENV MCP_COMPACT_SOURCE_ROOT=/opt/velxio-mcp-source
EXPOSE 80 8002
ENTRYPOINT ["/app/mcp-compact-entrypoint.sh"]
CMD []
