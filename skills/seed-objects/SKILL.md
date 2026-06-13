---

allowed-tools: Bash(curl *), Bash(python3 *), Bash(date *), Bash(grep *), Read, Grep
argument-hint: "[--universities N] [--students N] [--subjects N] [--entries N] [--scope company|site] [--url http://host:port]"
description: Seed a demo Objects dataset through the Headless REST API — a relational University / Student / Subject model plus a root-object (inheritance) Building tree — with their relationships and linked sample entries. Use when asked for an objects demo dataset, related objects, a root object / object tree, or data to test import/export or headless.
name: seed-objects

---

# Seed Objects

Build a demo Objects dataset on a running Liferay instance, covering both relationship styles in one pass:

- **Relational cluster** (plain relationships, `edge: false`) — **University**, **Student**, **Subject** with foreign-key and many-to-many links between entries.
- **Root-object cluster** (inheritance, `edge: true`) — a **Building** root object with **Classroom** and **Laboratory** children bound to it, each with its own entries.

All calls go through `../../rules/object-admin-rest-api.md`.

```
Relational (edge:false)            Root object / inheritance (edge:true)
University 1 ──< Student            Building (root)
University 1 ──< Subject            ├── Classroom   (bound)
Student   M >──< Subject            └── Laboratory  (bound)
```

## Input

Resolve from `${ARGUMENTS}`, falling back to the defaults:

- **`--universities N`** — universities to seed. Defaults to `2` (e.g. MIT, Stanford).
- **`--students N`** — students per university. Defaults to `3`.
- **`--subjects N`** — subjects per university. Defaults to `3`.
- **`--entries N`** — entries per root-object definition (Building, Classroom, Laboratory). Defaults to `2`.
- **`--scope`** — `company` or `site`. Defaults to `company`.
- **`--url`** — base URL of the target instance. Defaults to `http://localhost:8080`.

Definition names carry a timestamp suffix (e.g. `University143052`) so repeated runs do not collide; report the labels, which stay clean. Every definition is created with `panelCategoryKey: "control_panel.object"` so it appears in the UI under **Control Panel → Objects**.

## Procedure

Run the whole sequence without pausing for confirmation; it only creates data on a development instance.

### 1. Confirm the Target

Set `BASE` from `--url`, `AUTH="test@liferay.com:test"`, `ADMIN="${BASE}/o/object-admin/v1.0"`, and probe per the rule. Abort with a clear message when the probe is not `200`.

### 2. Create the Definitions (Draft)

Create all definitions with `POST ${ADMIN}/object-definitions`, each with `Text`/`String` fields and `panelCategoryKey: "control_panel.object"`:

- Relational — **University** (`name` required, `location`), **Student** (`name` required, `email`), **Subject** (`name` required, `code`).
- Root object — **Building** (`name` required, `address`), **Classroom** (`name` required, `seats`), **Laboratory** (`name` required, `equipment`).

Capture each `id`, and Building's `externalReferenceCode`.

### 3. Wire the Relationships

Create on the parent/`objectDefinitionId1` side, **before publishing**:

- Relational, `edge: false`: `oneToMany` University → Student (`students`); `oneToMany` University → Subject (`subjects`); `manyToMany` Student → Subject (`enrolledSubjects`).
- Inheritance, `edge: true`: `oneToMany` Building → Classroom (`classrooms`); `oneToMany` Building → Laboratory (`laboratories`). Binding sets each child's `rootObjectDefinitionExternalReferenceCode` to Building's `externalReferenceCode`.

### 4. Publish

`POST ${ADMIN}/object-definitions/${ID}/publish` for all six definitions.

### 5. Seed and Link Entries

Read each definition's `restContextPath`, then:

1. **Relational** — create `--universities` University entries. For each university, create `--students` Student and `--subjects` Subject entries, setting each one's University foreign-key field (discover it per the rule: the `Relationship` object field whose name contains the relationship name) to that university's entry `id`. Then enroll each student in a couple of that university's subjects through the `manyToMany` nested endpoint `PUT ${BASE}${STUDENT_REST_CONTEXT_PATH}/${STUDENT_ID}/enrolledSubjects/${SUBJECT_ID}`, varying the pairings.
2. **Root object** — create `--entries` entries in each of Building, Classroom, and Laboratory. A bound child's entries are independent of the root's entries — do not link them by foreign key.

### 6. Verify and Report

Confirm a sample student's University foreign key resolves and that `GET .../${STUDENT_ID}/enrolledSubjects` returns the expected subjects; confirm Classroom's and Laboratory's `rootObjectDefinitionExternalReferenceCode` equals Building's `externalReferenceCode`. Report two tables (relational, root object) of definitions with `id`, label, and `restContextPath`, the entry counts per definition, a few example enrollments, and the admin UI link (`${BASE}/group/control_panel/manage?p_p_id=com_liferay_object_web_internal_object_definitions_portlet_ObjectDefinitionsPortlet`).

## Notes

- The two clusters are independent: the relational one demonstrates entry-level links (`oneToMany` foreign key set in the child entry's body; `manyToMany` through the nested `PUT` named after the relationship), while the root-object one demonstrates definition-level inheritance (`edge: true`), where children are bound to the root but their entries stand alone.
- To remove the dataset afterwards, follow the rule's cleanup order: for every relationship `PUT` it with `edge: false` (this also disables inheritance on the `edge: true` ones), `DELETE` the relationships, then `DELETE` the children before their parent/root.
