ARG RUNTIME_IMAGE=agent-platform-runtime:slim
FROM ${RUNTIME_IMAGE}
ENV SERVICE_ROLE=model_gateway
ENV MODEL_GATEWAY_URL=
ENV PORT=8003
CMD ["uvicorn", "app.model.gateway_service:app", "--host", "0.0.0.0", "--port", "8003"]
