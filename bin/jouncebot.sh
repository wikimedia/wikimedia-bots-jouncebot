#!/usr/bin/env bash
# Management script for jouncebot kubernetes processes

set -e

DEPLOYMENT=jouncebot.libera
POD_NAME=jouncebot.libera

CONFIG=etc/secrets-libera.yaml
KUBECTL=/usr/bin/kubectl

TOOL_DIR=$(cd $(dirname $0)/.. && pwd -P)
VENV=venv-k8s-py37
if [[ -f ${TOOL_DIR}/${VENV}/bin/activate ]]; then
    source ${TOOL_DIR}/${VENV}/bin/activate
fi

_get_pod() {
    ${KUBECTL} get pods \
        --output=jsonpath={.items..metadata.name} \
        --selector=name=${POD_NAME}
}

case "$1" in
    start)
        echo "Starting jouncebot k8s deployment..."
        ${KUBECTL} create -f ${TOOL_DIR}/etc/deployment.yaml
        ;;
    run)
        date +%Y-%m-%dT%H:%M:%S
        echo "Running jouncebot..."
        cd ${TOOL_DIR}
        exec python3 jouncebot.py --config ${CONFIG} --verbose
        ;;
    stop)
        echo "Stopping jouncebot k8s deployment..."
        ${KUBECTL} delete deployment ${DEPLOYMENT}
        # FIXME: wait for the pods to stop
        ;;
    restart)
        echo "Restarting jouncebot k8s pod..."
        ${KUBECTL} delete pod $(_get_pod)
        ;;
    status)
        echo "Active pods:"
        ${KUBECTL} get pods -l name=${POD_NAME}
        ;;
    tail)
        exec ${KUBECTL} logs -f $(_get_pod)
        ;;
    update)
        echo "Updating git clone..."
        cd ${TOOL_DIR}
        git fetch &&
        git --no-pager log --stat HEAD..@{upstream} &&
        git rebase @{upstream}
        ;;
    attach)
        echo "Attaching to pod..."
        exec ${KUBECTL} exec -i -t $(_get_pod) -- /bin/bash
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|tail|update|attach}"
        exit 1
        ;;
esac

exit 0
# vim:ft=sh:sw=4:ts=4:sts=4:et:
