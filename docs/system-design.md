# Stackplan system design

## Objective

Stackplan is a school-scale DevOps and AI system. It demonstrates separation of
responsibilities, container orchestration, persistence, deterministic safety
checks and automated testing without adding production infrastructure that the
assignment does not need.

## Component flow

```text
Future frontend
      |
      v
helpers/api_helper.py
      |
      +---- uploaded evidence ----+
                                  v
                            src/main.py
                                  |
            +---------------------+---------------------+
            v                     v                     v
       IO Manager            AI Manager           Logic Manager
       safe intake       extraction/advice     weekly placement
            \_____________________|_____________________/
                                  |
                                  v
                           Data Manager
                                  |
                                  v
                         PostgreSQL container
```

## Core manager boundaries

### IO Manager

- Validates payload types and local image safety.
- Copies validated evidence into temporary working storage.
- Removes unusable modules while flushing hard errors forward.

### AI Manager

- Runs relevance, interpretation and normalization passes.
- Expands repeated assessments locally after model interpretation.
- Protects repeated group weights from accidental multiplication.
- Generates work checklists and trimester revision plans.
- Validates recommendation links, weeks and available hours locally.

### Logic Manager

- Converts normalized schedules into Week 1-14 buckets.
- Never invents unknown recurrence ranges.
- Ranks comparable assessments using credit and explicit module weight.
- Preserves unresolved assessments for human review.

### Data Manager

- Owns every SQL statement.
- Stores pipeline and recommendation history transactionally.
- Keeps confirmed revisions safe from later AI reruns.
- Provides the source-hash/model/prompt cache.

### Main

`main.py` is a linear coordinator. It does not reimplement manager checks and
does not contain a workflow framework.

## Database design

The assignment uses four tables:

```text
projects
  |-- pipeline_runs
  |-- module_results (versioned JSONB)
  `-- recommendations (separate JSONB advice)
```

JSONB is deliberate. AI Manager already owns the nested assessment contract;
duplicating every assessment field into relational tables would increase code
and schema coupling without helping the assignment's queries.

The schema is initialized from one SQL file. There is no migration framework.
Development schema changes recreate the local volume, and workflow tests always
start from a disposable database.

## Evidence versus advice

```text
image evidence -> confirmed module facts -> deterministic schedule
                                           |
                                           v
                                  AI recommendation candidate
```

Recommendation output is stored separately. It cannot mutate assessment facts
and must be accepted or dismissed by the user.

## Failure policy

- Hard errors use manager-specific prefixes and remain in the result list.
- A failed module does not stop other modules.
- Soft uncertainty remains module follow-up metadata.
- PostgreSQL writes use transactions and roll back together.
- Complete pipeline failure returns a non-zero CLI status.
- Partial success remains available and is recorded as partial.

## DevOps evidence

- Multi-stage non-root application image.
- PostgreSQL health checks and startup dependency.
- Persistent development volume.
- Disposable test database.
- Separate runtime and test image targets.
- Environment-based secrets.
- Offline deterministic AI fixtures.
- Function and workflow test separation.
- Provider request duration logging.

The design intentionally omits Kubernetes, Redis, message queues, an ORM and a
migration framework because they would add ceremony without improving the
assignment outcome.
