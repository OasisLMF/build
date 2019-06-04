#!/usr/bin/env bash
echo 'pipeline.sh '$@

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"



pipeline_print_funcs(){
    # This prints all defined functions, except for those named pipeline 
    compgen -A function | grep -v pipeline
}
print_model_vars(){
    set +eux
    printf ' ---- Shell Build Variables ----------- \n' 
    printf "export TAG_RELEASE=$TAG_RELEASE\n"
    printf "export TAG_RUN_PLATFORM=$TAG_RUN_PLATFORM\n"
    printf "export TAG_RUN_WORKER=$TAG_RUN_WORKER\n"

    printf "export IMAGE_WORKER=$IMAGE_WORKER\n"

    printf "export MODEL_SUPPLIER=$MODEL_SUPPLIER\n"
    printf "export MODEL_VARIENT=$MODEL_VARIENT\n"
    printf "export MODEL_ID=$MODEL_ID\n"
    printf "export TEST_MAX_RUNTIME=$TEST_MAX_RUNTIME\n"

    printf "export TEST_DATA_DIR=$TEST_DATA_DIR\n"
    printf "export OASIS_MODEL_DATA_DIR=$OASIS_MODEL_DATA_DIR\n"
    printf "export COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME\n"

    #printf "export VERS_KEYS_DATA=$VERS_KEYS_DATA\n"
    #printf "export VERS_MODEL_DATA=$VERS_MODEL_DATA\n"
    #printf "export PATH_MODEL_DATA=$PATH_MODEL_DATA\n"
    #printf "export PATH_KEYS_DATA=$PATH_KEYS_DATA\n"
    #printf "export PATH_TEST_DIR=$PATH_TEST_DIR\n"
    printf ' -------------------------------------- \n'
}

pipeline_help() {
	# catch 
    cat <<EOF
pipeline is a wrapper for building environments for the OASIS build pipeline.
Functions are defined bash files and loaded using the PATH syntax

Example:
  export PIPELINE_LOAD="./catrisks.sh:./build-oasis-api.sh"
  ./pipeline.sh <defined_function>

Usage:
  pipeline [command]

Available Commands:
EOF
pipeline_print_funcs
    exit 1
}

pipeline_load(){
    # This function selectively sources scripts based on the env var below
    # export PIPELINE_LOAD='/path/to/catrisk.sh:/path/to/flamingo.sh'

    if [ -n "$PIPELINE_LOAD" ]; then 
        #Set delimiter & load array
        IFS=':'; set -f
        scripts_array=($PIPELINE_LOAD)

        # Iterate over array and source scripts
        for script in "${scripts_array[@]}"
        do  
            echo "Loading: " $script
            source $script
        done
	IFS="$oIFS"
    else    
        echo "Error: '\$PIPELINE_LOAD' is not set"
        echo
        pipeline_help
        exit 1
    fi     
}

# load build scripts
pipeline_load

# Check for args
if [ "$#" -lt 1 ] || [ "$1" == "help" ] ; then
    pipeline_help
    exit 1
fi

# check that the arg is a defined function and exec
if [ -n "$(type -t $1)" ]; then 
	echo Exec: $@
    set -eux
	eval "$@"
else 
	pipeline_help
	exit 1
fi
