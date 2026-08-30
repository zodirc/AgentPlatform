ARG RUNTIME_IMAGE=agent-platform-runtime:slim
FROM ${RUNTIME_IMAGE}
ENV SERVICE_ROLE=sandbox
ENV SANDBOX_PLANE_URL=
ENV PORT=8004
CMD ["uvicorn", "app.sandbox_plane.service:app", "--host", "0.0.0.0", "--port", "8004"]
