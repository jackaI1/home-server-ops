FROM python:3.13-slim-trixie
# Refresh OS fixes on every build; the application has no third-party runtime dependencies.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chown=10001:10001 automation/ /app/automation/
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "automation.server"]
