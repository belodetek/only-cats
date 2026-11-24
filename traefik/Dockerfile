FROM traefik@sha256:63f61f603052fbcc77597da1dc71ed8c39cf3f3e5a7c92c73bc94d84973997c3

RUN apk add --no-cache tzdata

RUN mkdir -p /etc/traefik/dynamic

COPY dynamic/ /etc/traefik/dynamic/
