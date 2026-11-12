ARG PYTHON_IMAGE=python:3.13-slim
# Supply --build-context cockpit-seed=<delivery-seed-dir>.
FROM scratch AS cockpit-seed
# Supply --build-context builtin-ontology=<customer-config-ontology-dir>.
FROM scratch AS builtin-ontology
FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PROCESS360_BUILTIN_CATALOG_PATH=/app/builtin-ontology/catalog.json
WORKDIR /app
COPY --from=wheelhouse / /wheels/
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && pip check && rm -rf /wheels
COPY bi_agent/ /app/bi_agent/
COPY --from=cockpit-seed /frozen-annual.json /app/bi_agent/cockpit/frozen-annual.json
COPY --from=builtin-ontology / /app/builtin-ontology/
COPY open_claude/ /app/open_claude/
COPY ontology-analytics-mcp/ /app/ontology-analytics-mcp/
COPY .claude/agents/ /app/.claude/agents/
COPY dataset/process360/ywln-v3.1/ /app/dataset/process360/ywln-v3.1/
COPY LICENSE /app/LICENSE
RUN mkdir -p /app/dataset/customer /app/dataset/cockpit /app/dataset/process360-state
EXPOSE 8080
CMD ["python","-m","bi_agent.web.customer"]
