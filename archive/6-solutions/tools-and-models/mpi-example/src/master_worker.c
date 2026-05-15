/*
 * master_worker.c
 *
 * A generic MPI master-worker pattern demonstrating task distribution
 * and result collection. This example reads input files from a mounted
 * directory and processes them in parallel.
 *
 * The master node (rank 0) discovers input files, distributes them to workers,
 * implements dynamic load balancing, and collects results. Workers process 
 * files and return results until receiving a termination signal.
 */
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#include <errno.h>

#define MAX_FILENAME_LEN        256
#define MAX_PATH_LEN            512
#define MAX_LINE_LEN            1024
#define MAX_TASKS               10000
#define MSG_TERMINATE           (-1)
#define WORK_TAG                1
#define RESULT_TAG              2
#define DEFAULT_INPUT_DIR       "/app/inputs"
#define DEFAULT_OUTPUT_DIR      "/app/outputs"

#define LOG(...)        fprintf(stderr, __VA_ARGS__)
#define INFO(...)       LOG("[INFO] " __VA_ARGS__)
#define ERROR(...)      LOG("[ERROR] " __VA_ARGS__)
#ifdef DEBUG_MODE
  #define DEBUG(...)    LOG("[DEBUG] " __VA_ARGS__)
#else
  #define DEBUG(...)
#endif

/* Structure to identify MPI process */
struct mpi_identity
{
    int     processors;
    int     rank;
    int     namelen;
    char    name[MPI_MAX_PROCESSOR_NAME];
};

/* Task structure - what workers receive */
typedef struct {
    int task_id;
    char filename[MAX_FILENAME_LEN];
    char input_path[MAX_PATH_LEN];
} Task;

/* Result structure - what workers send back */
typedef struct {
    int task_id;
    char filename[MAX_FILENAME_LEN];
    int lines_processed;
    int numbers_sum;
    int worker_rank;
    char worker_name[MPI_MAX_PROCESSOR_NAME];
    char status[64];
} Result;

static struct mpi_identity
mpi_whoami(void)
{
    struct mpi_identity id;

    MPI_Comm_size(MPI_COMM_WORLD, &id.processors);
    MPI_Comm_rank(MPI_COMM_WORLD, &id.rank);
    MPI_Get_processor_name(id.name, &id.namelen);

    return id;
}

/* Discover all input files in the specified directory */
static int
discover_input_files(const char *input_dir, char filenames[][MAX_FILENAME_LEN], int max_files)
{
    DIR *dir;
    struct dirent *entry;
    struct stat statbuf;
    char filepath[MAX_PATH_LEN];
    int count = 0;
    
    dir = opendir(input_dir);
    if (!dir) {
        ERROR("Failed to open input directory: %s (errno=%d: %s)\n", 
              input_dir, errno, strerror(errno));
        return -1;
    }
    
    INFO("Scanning directory: %s\n", input_dir);
    
    while ((entry = readdir(dir)) != NULL && count < max_files) {
        /* Skip . and .. */
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        
        /* Build full path */
        snprintf(filepath, sizeof(filepath), "%s/%s", input_dir, entry->d_name);
        
        /* Check if it's a regular file */
        if (stat(filepath, &statbuf) == 0 && S_ISREG(statbuf.st_mode)) {
            size_t len = strlen(entry->d_name);
            if (len >= MAX_FILENAME_LEN) len = MAX_FILENAME_LEN - 1;
            memcpy(filenames[count], entry->d_name, len);
            filenames[count][len] = '\0';
            DEBUG("Found input file: %s\n", filenames[count]);
            count++;
        }
    }
    
    closedir(dir);
    
    INFO("Discovered %d input files\n", count);
    return count;
}

/* Process a single input file - example: read numbers and sum them */
static Result
process_file(const Task *task, const char *input_dir, struct mpi_identity *id)
{
    Result result = {0};
    result.task_id = task->task_id;
    result.worker_rank = id->rank;
    
    size_t len = strlen(task->filename);
    if (len >= MAX_FILENAME_LEN) len = MAX_FILENAME_LEN - 1;
    memcpy(result.filename, task->filename, len);
    result.filename[len] = '\0';
    
    len = strlen(id->name);
    if (len >= MPI_MAX_PROCESSOR_NAME) len = MPI_MAX_PROCESSOR_NAME - 1;
    memcpy(result.worker_name, id->name, len);
    result.worker_name[len] = '\0';
    
    char filepath[MAX_PATH_LEN];
    snprintf(filepath, sizeof(filepath), "%s/%s", input_dir, task->filename);
    
    FILE *fp = fopen(filepath, "r");
    if (!fp) {
        snprintf(result.status, sizeof(result.status), "ERROR: Cannot open file");
        ERROR("Worker #%d failed to open: %s\n", id->rank, filepath);
        return result;
    }
    
    char line[MAX_LINE_LEN];
    int lines = 0;
    int sum = 0;
    
    /* Read file line by line and sum up numbers */
    while (fgets(line, sizeof(line), fp)) {
        lines++;
        
        /* Parse numbers from the line */
        char *ptr = line;
        while (*ptr) {
            if (*ptr >= '0' && *ptr <= '9') {
                int num = atoi(ptr);
                sum += num;
                /* Skip to next non-digit */
                while (*ptr >= '0' && *ptr <= '9') ptr++;
            } else {
                ptr++;
            }
        }
        
        /* Simulate some processing time */
        usleep(10000); /* 10ms per line */
    }
    
    fclose(fp);
    
    result.lines_processed = lines;
    result.numbers_sum = sum;
    snprintf(result.status, sizeof(result.status), "SUCCESS");
    
    return result;
}

/* Master node logic */
static void
run_master(struct mpi_identity id, const char *input_dir, const char *output_dir)
{
    INFO("Master node started with %d workers\n", id.processors - 1);
    
    int num_workers = id.processors - 1;
    
    /* Discover input files */
    char (*filenames)[MAX_FILENAME_LEN] = malloc(sizeof(char[MAX_TASKS][MAX_FILENAME_LEN]));
    if (!filenames) {
        ERROR("Failed to allocate memory for filenames\n");
        return;
    }
    
    int total_tasks = discover_input_files(input_dir, filenames, MAX_TASKS);
    if (total_tasks <= 0) {
        ERROR("No input files found in %s\n", input_dir);
        free(filenames);
        return;
    }
    
    INFO("Processing %d files with %d workers\n", total_tasks, num_workers);
    
    /* Allocate results array */
    Result *results = malloc(sizeof(Result) * total_tasks);
    if (!results) {
        ERROR("Failed to allocate memory for results\n");
        free(filenames);
        return;
    }
    
    int tasks_sent = 0;
    int tasks_completed = 0;
    time_t start_time = time(NULL);
    
    /* Initial task distribution - send one task to each worker */
    for (int worker = 1; worker <= num_workers && tasks_sent < total_tasks; worker++) {
        Task task = {0};
        task.task_id = tasks_sent;
        
        size_t len = strlen(filenames[tasks_sent]);
        if (len >= MAX_FILENAME_LEN) len = MAX_FILENAME_LEN - 1;
        memcpy(task.filename, filenames[tasks_sent], len);
        task.filename[len] = '\0';
        
        len = strlen(input_dir);
        if (len >= MAX_PATH_LEN) len = MAX_PATH_LEN - 1;
        memcpy(task.input_path, input_dir, len);
        task.input_path[len] = '\0';
        
        MPI_Send(&task, sizeof(Task), MPI_BYTE, worker, WORK_TAG, MPI_COMM_WORLD);
        INFO("Sent task %d (file=%s) to worker %d\n", task.task_id, task.filename, worker);
        tasks_sent++;
    }
    
    /* Dynamic load balancing: collect results and dispatch more work */
    while (tasks_completed < total_tasks) {
        Result result;
        MPI_Status status;
        
        /* Receive result from any worker */
        MPI_Recv(&result, sizeof(Result), MPI_BYTE, MPI_ANY_SOURCE, RESULT_TAG, 
                 MPI_COMM_WORLD, &status);
        
        int worker = status.MPI_SOURCE;
        
        /* Store the result */
        results[result.task_id] = result;
        tasks_completed++;
        
        DEBUG("Received result for task %d from worker %d: %s (lines=%d, sum=%d) [%d/%d completed]\n",
              result.task_id, worker, result.filename, result.lines_processed, 
              result.numbers_sum, tasks_completed, total_tasks);
        
        /* Send more work if available */
        if (tasks_sent < total_tasks) {
            Task task = {0};
            task.task_id = tasks_sent;
            
            size_t len = strlen(filenames[tasks_sent]);
            if (len >= MAX_FILENAME_LEN) len = MAX_FILENAME_LEN - 1;
            memcpy(task.filename, filenames[tasks_sent], len);
            task.filename[len] = '\0';
            
            len = strlen(input_dir);
            if (len >= MAX_PATH_LEN) len = MAX_PATH_LEN - 1;
            memcpy(task.input_path, input_dir, len);
            task.input_path[len] = '\0';
            
            MPI_Send(&task, sizeof(Task), MPI_BYTE, worker, WORK_TAG, MPI_COMM_WORLD);
            DEBUG("Sent task %d (file=%s) to worker %d\n", task.task_id, task.filename, worker);
            tasks_sent++;
        } else {
            /* No more work, send termination signal */
            Task terminate_task = { .task_id = MSG_TERMINATE };
            MPI_Send(&terminate_task, sizeof(Task), MPI_BYTE, worker, WORK_TAG, MPI_COMM_WORLD);
            DEBUG("Sent termination signal to worker %d\n", worker);
        }
        
        /* Progress indicator */
        if (tasks_completed % 10 == 0 || tasks_completed == total_tasks) {
            INFO("Progress: %d/%d files processed (%.1f%%)\r", 
                 tasks_completed, total_tasks, 
                 (tasks_completed * 100.0) / total_tasks);
        }
    }
    
    time_t end_time = time(NULL);
    double elapsed = difftime(end_time, start_time);
    
    INFO("\n=== All files processed in %.2f seconds ===\n", elapsed);
    INFO("Total files: %d\n", total_tasks);
    INFO("Workers used: %d\n", num_workers);
    INFO("Average time per file: %.3f seconds\n", elapsed / total_tasks);
    
    /* Write results to output file */
    char output_file[MAX_PATH_LEN];
    snprintf(output_file, sizeof(output_file), "%s/results.txt", output_dir);
    
    FILE *fp = fopen(output_file, "w");
    if (fp) {
        fprintf(fp, "MPI Master-Worker Processing Results\n");
        fprintf(fp, "====================================\n\n");
        fprintf(fp, "Total files processed: %d\n", total_tasks);
        fprintf(fp, "Total time: %.2f seconds\n", elapsed);
        fprintf(fp, "Workers used: %d\n\n", num_workers);
        fprintf(fp, "%-8s | %-30s | %-8s | %-12s | %-10s | %-30s | %s\n", 
                "Task ID", "Filename", "Lines", "Numbers Sum", "MPI Rank", "Worker Node", "Status");
        fprintf(fp, "---------|--------------------------------|----------|--------------|------------|--------------------------------|----------\n");
        
        int total_lines = 0;
        int total_sum = 0;
        
        for (int i = 0; i < total_tasks; i++) {
            fprintf(fp, "%-8d | %-30s | %-8d | %-12d | %-10d | %-30s | %s\n", 
                    results[i].task_id,
                    results[i].filename,
                    results[i].lines_processed,
                    results[i].numbers_sum,
                    results[i].worker_rank,
                    results[i].worker_name,
                    results[i].status);
            
            if (strcmp(results[i].status, "SUCCESS") == 0) {
                total_lines += results[i].lines_processed;
                total_sum += results[i].numbers_sum;
            }
        }
        
        fprintf(fp, "\n");
        fprintf(fp, "Summary:\n");
        fprintf(fp, "  Total lines processed: %d\n", total_lines);
        fprintf(fp, "  Total sum of numbers: %d\n", total_sum);
        
        fclose(fp);
        INFO("Results written to %s\n", output_file);
    } else {
        ERROR("Failed to write results file: %s\n", output_file);
    }
    
    free(results);
    free(filenames);
}

/* Worker node logic */
static void
run_worker(struct mpi_identity id, const char *input_dir)
{
    INFO("Worker node #%d (%.*s) ready for work\n", id.rank, id.namelen, id.name);
    
    int tasks_processed = 0;
    
    while (1) {
        Task task;
        MPI_Status status;
        
        /* Receive task from master */
        MPI_Recv(&task, sizeof(Task), MPI_BYTE, 0, WORK_TAG, MPI_COMM_WORLD, &status);
        
        /* Check for termination signal */
        if (task.task_id == MSG_TERMINATE) {
            INFO("Worker #%d received termination signal (processed %d files)\n", 
                 id.rank, tasks_processed);
            break;
        }
        
        DEBUG("Worker #%d processing task %d (file=%s)\n", 
              id.rank, task.task_id, task.filename);
        
        /* Process the file */
        Result result = process_file(&task, input_dir, &id);
        
        /* Send result back to master */
        MPI_Send(&result, sizeof(Result), MPI_BYTE, 0, RESULT_TAG, MPI_COMM_WORLD);
        
        DEBUG("Worker #%d completed task %d: %s (lines=%d, sum=%d)\n", 
              id.rank, task.task_id, result.filename, result.lines_processed, result.numbers_sum);
        
        tasks_processed++;
    }
    
    INFO("Worker #%d shutting down\n", id.rank);
}

int
main(int argc, char** argv)
{
    int rc = 1;
    
    /* Get input and output directories from environment or use defaults */
    const char *input_dir = getenv("INPUT_DIR");
    if (!input_dir) input_dir = DEFAULT_INPUT_DIR;
    
    const char *output_dir = getenv("OUTPUT_DIR");
    if (!output_dir) output_dir = DEFAULT_OUTPUT_DIR;
    
    /* Initialize MPI */
    if (MPI_Init(&argc, &argv) != MPI_SUCCESS) {
        ERROR("Failed to initialize MPI\n");
        goto error;
    }
    
    /* Identify this process */
    struct mpi_identity id = mpi_whoami();
    INFO("MPI Process %d/%d on %.*s\n", id.rank, id.processors, id.namelen, id.name);
    
    /* Check minimum requirements */
    if (id.processors < 2) {
        ERROR("Need at least 2 MPI processes (1 master + 1 worker)\n");
        ERROR("Run with: mpirun -np <N> ./master_worker (where N >= 2)\n");
        goto error;
    }
    
    /* Print configuration */
    if (id.rank == 0) {
        INFO("Configuration:\n");
        INFO("  Input directory:  %s\n", input_dir);
        INFO("  Output directory: %s\n", output_dir);
    }
    
    /* Seed random number generator differently for each process */
    srand(time(NULL) + id.rank);
    
    /* Branch based on rank */
    if (id.rank == 0) {
        run_master(id, input_dir, output_dir);
    } else {
        run_worker(id, input_dir);
    }
    
    /* Finalize MPI */
    MPI_Finalize();
    
    rc = 0;
error:
    return rc;
}
