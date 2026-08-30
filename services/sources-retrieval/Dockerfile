# ADR-020: thin image on top of the shared runtime bake.
ARG RUNTIME_IMAGE=agent-platform-runtime:default
FROM ${RUNTIME_IMAGE}
ENV SERVICE_ROLE=retrieval
ENV PORT=8001
CMD ["uvicorn", "app.retrieval.service:app", "--host", "0.0.0.0", "--port", "8001"]
