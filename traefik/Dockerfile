FROM traefik@sha256:aa942a00bce033c909bf1f7e861d93761be4b31a035f10d2410d33e38a8f41cf

RUN apk add --no-cache tzdata

RUN mkdir -p /etc/traefik/dynamic

COPY dynamic/ /etc/traefik/dynamic/
