#!/usr/bin/env bash
# Generic bash functions

docker-check-tag(){
    local image=$1
    local tag=$2

    url="https://registry.hub.docker.com/v2/repositories/${image}/tags/${tag}/"
    response_code=$(curl -s -o /dev/null -w "%{http_code}" "${url}")
    echo $response_code
    if [ $response_code == "200" ]; then
        echo 'Tag exisits - not safe to push'
        return 0
    else
        return 1
    fi
}

git_tag(){
    if git rev-parse $1 >/dev/null 2>&1; then
        echo "Tag exisits -- skip"
    else
        git tag $1
        git push origin $1
    fi
}

prev_vers(){
    cat $1 | grep \` -m 1 | awk -F "\`" 'NR==1 {print $2}'
}    

build_image(){
    local DOCKER_FILE=$1
    local IMAGE_NAME=$2
    local RELEASE_TAG=$3

    if [ $# -gt 3 ]; then
        local BASE_IMG_TAG=$4
        sed -i "s/latest/${BASE_IMG_TAG}/g" $DOCKER_FILE
    fi

    docker-check-tag $IMAGE_NAME $RELEASE_TAG && exit 1
    docker build  --no-cache=true\
                 -t $IMAGE_NAME:${RELEASE_TAG}\
                 -t $IMAGE_NAME:latest\
                 -f $DOCKER_FILE .
}

# push-image $IMAGE_NAME $RELEASE_TAG
push_image() {
    local IMAGE_NAME=$1
    local RELEASE_TAG=$2
    docker push $IMAGE_NAME:$RELEASE_TAG
    docker push $IMAGE_NAME:latest
}
# purge-image $IMAGE_NAME $RELEASE_TAG
purge_image(){
    local IMAGE_NAME=$1
    local RELEASE_TAG=$2
    docker rmi -f $IMAGE_NAME:$RELEASE_TAG
}

compose_oasis(){
    local cmd='docker-compose'
    local server=' -f compose/oasis.platform.yml'
    echo ${cmd}${server}
}
compose_model(){
    local worker=' -f compose/model.worker.yml'
    echo $(compose_oasis)${worker}
}

wait_for_api_server(){
    host=$1

    SERVER_HEALTH=0
    until [ $SERVER_HEALTH -gt 0 ] ; do
      >&2 echo "Server is unavailable - sleeping"
      sleep 1
      echo "curl -X GET 'http://$host/healthcheck/'"
      SERVER_HEALTH=$(curl -X GET "http://$host/healthcheck/" -H "accept: application/json" | grep -c "OK") > /dev/null
    done
    echo "Server is available - exit"
}


start_oasis(){
    echo $(compose_oasis)" $@"' up -d'
}
stop_oasis(){
    local tester=' -f compose/model.tester.yml'
    echo $(compose_oasis)${tester}" $@"' down -v || true'
}

start_model(){
    eval $(compose_model)' up -d'
}
stop_model(){
    eval $(compose_model)' down -v || true'
}

# stop all containers matching RegEx
stop_docker(){
    uuid=$1
    printf "Stopping containers"
    docker ps | grep $uuid | awk 'BEGIN { FS = "[ \t\n]+" }{ print $1 }' | xargs -r docker stop
    printf "Deleting containers"
    docker ps -a | grep $uuid | awk 'BEGIN { FS = "[ \t\n]+" }{ print $1 }' | xargs -r docker rm
    printf "Deleting unused networks"
    yes | docker network prune
}

run_mdk(){
    set -o pipefail
    local py_ver=$1
    local model_branch=$2
    local mdk_branch=$3
    local mdk_run_mode=$4
    local log_file="MDK-runner_${py_ver}.log"
    docker build -f docker/Dockerfile.mdk-tester -t mdk-runner .
    docker run mdk-runner ${py_ver} run_model.py --model-repo-branch ${model_branch} --mdk-repo-branch ${mdk_branch} --model-run-mode ${mdk_run_mode} | tee stage/log/${log_file}

}


## new generic version 
run_test(){
    local tester=' -f compose/model.tester.yml'
    eval $(compose_model)${tester}' up -d'
    bash -c $(compose_oasis)$tester' logs -f --tail="all" worker | { sed "/Connected to amqp/ q" && kill -PIPE $$ ; }'  > /dev/null 2>&1
    eval $(compose_model)${tester}' run --rm --entrypoint="bash -c " model_tester "./runtest '"$@"'"'
}

run_ui(){
    local oasis_ui=' -f compose/oasis.ui.yml'
    start_oasis -f compose/oasis.ui.yml
    sleep 5
    stop_oasis -f compose/oasis.ui.yml
}

# OasisLMF python package
sign_oasislmf(){
    TAR_PKG=$(find ./dist/ -name "oasislmf-*.tar.gz")
    bash -c "echo ${PASSPHRASE} | gpg --batch --no-tty --passphrase-fd 0 --detach-sign -a ${TAR_PKG}"
}
push_oasislmf(){
    TAR_PKG=$(find ./dist/ -name "oasislmf-*.tar.gz")
    /usr/local/bin/twine upload $TAR_PKG $TAR_PKG.asc
}
set_vers_oasislmf(){
    OASISLMF_VERS=$1
    KTOOLS_VERS=$2
    PROJECT_INIT_PATH='./oasislmf/__init__.py'
    PROJECT_CONF_FILE='./setup.py'
    sed -i "/__version__ =/c\__version__ = '${OASISLMF_VERS}'" $PROJECT_INIT_PATH
    sed -i "/KTOOLS_VERSION =/c\KTOOLS_VERSION = '${KTOOLS_VERS}'" $PROJECT_CONF_FILE
}
commit_vers_oasislmf(){
    # push incremented version number to git
    OASISLMF_VERS=$1
    COMMIT_MSG="Upgrade to new version '${OASISLMF_VERS}'"
    if [ $(git status | grep -c oasislmf/__init__.py) -eq 1 ]; then
        git add ./oasislmf/__init__.py && git commit -m $COMMIT_MSG && git push origin
    else
        echo 'no changes to commit'
    fi
}