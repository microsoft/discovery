FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    VNC_PORT=5901 \
    NOVNC_PORT=6080 \
    VNC_PASSWORD=password

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv git curl wget tar ca-certificates \
    supervisor tigervnc-standalone-server tigervnc-common \
    openbox xterm libgl1-mesa-dev libglu1-mesa-dev libxrender1 libxi6 libxtst6 mesa-utils \
    net-tools iproute2 procps \
    && rm -rf /var/lib/apt/lists/*

RUN cd /opt && \
    git clone https://github.com/novnc/noVNC.git && cd noVNC && git checkout v1.4.0 && \
    cd /opt && git clone https://github.com/novnc/websockify.git && cd websockify && git checkout v0.11.0 && \
    python3 -m venv /opt/novnc-venv && \
    /opt/novnc-venv/bin/pip install --upgrade pip && \
    /opt/novnc-venv/bin/pip install -e /opt/websockify

ENV PATH="/opt/novnc-venv/bin:$PATH"

RUN useradd -m -s /bin/bash dev && \
    mkdir -p /home/dev/.vnc /home/dev/.config/openbox /var/log/supervisor && \
    chown -R dev:dev /home/dev /var/log/supervisor /opt/noVNC /opt/websockify

COPY --chown=dev:dev openbox-rc.xml /home/dev/.config/openbox/rc.xml
COPY --chown=dev:dev openbox-menu.xml /home/dev/.config/openbox/menu.xml

COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY run-novnc.sh /usr/local/bin/run-novnc.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/run-novnc.sh /usr/local/bin/entrypoint.sh

EXPOSE 6080

USER dev
WORKDIR /home/dev

# ENTRYPOINT [ "/bin/sh", "-c" ]
CMD ["/usr/local/bin/entrypoint.sh"]
