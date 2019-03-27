//JOB TEMPLATE 
def createStage(stage_name, stage_params, propagate_flag) {
    return {
        stage("Build: ${stage_name}") {
            build job: "./${stage_name}", parameters: stage_params, propagate: propagate_flag
        }
    }
}


node {
    hasFailed = false
    deleteDir()
    println(params)

    // Set Build PARAMS
    String releaseId = params.VERSION
    boolean publish = params.PUBLISH
    releaseId = (params.PUBLISH ? releaseId : "${releaseId}-dev.${env.BUILD_NUMBER}")
    String baseId  = ((params.BASE_IMAGE  == '') ? releaseId : params.BASE_IMAGE)

    job_params = [
        [$class: 'StringParameterValue',  name: 'BUILD_BRANCH', value: params.BUILD_BRANCH],
        [$class: 'StringParameterValue',  name: 'RELEASE_TAG', value: releaseId], 
        [$class: 'StringParameterValue',  name: 'BASE_TAG', value: baseId], 
        [$class: 'BooleanParameterValue', name: 'SLACK_MESSAGE', value: Boolean.valueOf(params.POST_TO_SLACK)],
        [$class: 'BooleanParameterValue', name: 'PUBLISH', value: Boolean.valueOf(publish)],
        [$class: 'BooleanParameterValue', name: 'PURGE', value: Boolean.valueOf(false)]
    ]

    try {
        //RUN SEQUENTIAL JOBS, Fail pipeline on error 
        if (params.SEQUENTIAL_JOB_LIST){
            jobs_sequential = params.SEQUENTIAL_JOB_LIST.split()
            for (pipeline in jobs_sequential){
                createStage(pipeline, job_params, true).call() 
            }
        }
        //RUN SEQUENTIAL JOBS, Continue on error 
        if (params.SEQUENTIAL_JOB_LIST_NOFAIL){
            jobs_sequential = params.SEQUENTIAL_JOB_LIST_NOFAIL.split()
            for (pipeline in jobs_sequential){
                createStage(pipeline, job_params, false).call() 
            }
        }
        //RUN PARALLEL JOBS
        if (params.PARALLEL_JOB_LIST){
            jobs_parallel   = params.PARALLEL_JOB_LIST.split()
            parallel jobs_parallel.collectEntries {
                ["${it}": createStage(it, job_params, true)]
            }
        }
    } catch(hudson.AbortException | org.jenkinsci.plugins.workflow.steps.FlowInterruptedException buildException) {
        hasFailed = true
        error('Build Failed')
    } finally {
        if (params.PURGE){
            sh 'set +exu'
            sh 'docker rmi --force $(docker images | grep ' + releaseId + ' | awk \'BEGIN { FS = "[ \\t\\n]+" }{ print $3 }\')'
            sh 'docker volume ls -qf dangling=true | xargs -r docker volume rm'
        }

        if(hasFailed) {
            //Error handling (if extra cleanup needed)
        }
    }
}
