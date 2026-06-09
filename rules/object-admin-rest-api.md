# Object Admin REST API

Use these procedures whenever a skill creates, reads, or deletes Liferay Objects (object definitions, relationships, or entries) through the Headless REST API. Every interaction is a `curl` call against a running Liferay instance.

## Target Instance and Authentication

Default to a local bundle at `http://localhost:8080` authenticated as the default admin with HTTP basic auth `test@liferay.com:test`.

```bash
BASE="http://localhost:8080"
AUTH="test@liferay.com:test"
ADMIN="${BASE}/o/object-admin/v1.0"
```

Confirm the instance answers before doing any work:

```bash
curl --silent --output /dev/null --write-out "%{http_code}" \
	--user "${AUTH}" "${ADMIN}/object-definitions?pageSize=1"
```

A `200` means ready. When the probe fails, the portal is either down or on another port: resolve the HTTP port from the running Tomcat's `conf/server.xml` (the `port` on the `protocol="HTTP/1.1"` connector — see the portal's `tomcat.md` rule), or accept a `--url` override from the caller. Never hardcode a non-8080 port.

## Object Definitions

Create a definition (it starts as a draft, `active: false`). `name` is alphanumeric, starts with an uppercase letter, and carries no spaces; Liferay prefixes the storage table with `C_`. `scope` is `company` or `site`. At least one `objectField` is required.

```bash
curl --silent --request POST --user "${AUTH}" \
	--header "Content-Type: application/json" \
	--url "${ADMIN}/object-definitions" \
	--data '{
		"label": {"en_US": "My Object"},
		"pluralLabel": {"en_US": "My Objects"},
		"name": "MyObject",
		"scope": "company",
		"objectFields": [
			{
				"label": {"en_US": "Title"},
				"name": "title",
				"businessType": "Text",
				"type": "String"
			}
		]
	}'
```

Set `panelCategoryKey` to `"control_panel.object"` (accepted on create or `PATCH`) so the definition's entries application is reachable from the UI under **Control Panel → Objects**; without it the entries are only visible through this REST API.

The response carries the `id`, the `externalReferenceCode`, and an `actions` block whose `publish` href is the publish endpoint. Entries cannot be created until the definition is published:

```bash
curl --silent --request POST --user "${AUTH}" \
	--url "${ADMIN}/object-definitions/${OBJECT_DEFINITION_ID}/publish"
```

Read a definition to recover its `restContextPath` (the entry endpoint, e.g. `/o/c/myobjects`) and its `rootObjectDefinitionExternalReferenceCode`:

```bash
curl --silent --user "${AUTH}" \
	--url "${ADMIN}/object-definitions/${OBJECT_DEFINITION_ID}"
```

## Inheritance (Parent/Child Binding)

Liferay has no field-level inheritance between object definitions. The parent/child structure the UI labels **inheritance** is an object **relationship** with `edge: true`, created on the parent. Binding sets the child's read-only `rootObjectDefinitionExternalReferenceCode` to the parent's `externalReferenceCode`, marking the child as part of the parent's tree. Create the edge **before** publishing the child.

```bash
curl --silent --request POST --user "${AUTH}" \
	--header "Content-Type: application/json" \
	--url "${ADMIN}/object-definitions/${PARENT_ID}/object-relationships" \
	--data '{
		"objectDefinitionId1": '"${PARENT_ID}"',
		"objectDefinitionId2": '"${CHILD_ID}"',
		"name": "myChildren",
		"label": {"en_US": "My Children"},
		"type": "oneToMany",
		"deletionType": "cascade",
		"edge": true
	}'
```

`edge: true` (a bound tree) and entry-to-entry foreign keys are mutually exclusive through the entry API: a bound child's entries are independent of any parent entry, so do not attempt to set a relationship foreign key on a bound child's entries. Use `edge: false` only when the goal is a plain relationship whose child entries reference a parent entry by foreign key.

## Plain Relationships and Entry Linking

A plain relationship (`edge: false`) links entries by their type:

- **`oneToMany`** creates a foreign-key object field on the **many** side (the child definition), named `r_<relationshipName>_c_<parentName>Id`. Discover it by reading the child definition and taking the `objectField` whose `businessType` is `Relationship` and whose name contains the relationship name. Link a child entry to a parent entry by setting that field to the parent entry's `id` in the child entry's body.

- **`manyToMany`** creates **no** object field on either side; it is a join. Link two existing entries through the nested endpoint exposed under the relationship name, taking the relationship name as the path segment:

	```bash
	curl --silent --request PUT --user "${AUTH}" \
		--url "${BASE}${LEFT_REST_CONTEXT_PATH}/${LEFT_ENTRY_ID}/${RELATIONSHIP_NAME}/${RIGHT_ENTRY_ID}"
	```

	`GET ${BASE}${LEFT_REST_CONTEXT_PATH}/${LEFT_ENTRY_ID}/${RELATIONSHIP_NAME}` lists the related entries. A plain relationship deletes directly (`DELETE ${ADMIN}/object-relationships/${RELATIONSHIP_ID}`), without the disable-inheritance step.

## Object Entries

Entries are created against the definition's `restContextPath`. Object field values are flat top-level keys (not nested under `properties`). Required fields must be present.

```bash
curl --silent --request POST --user "${AUTH}" \
	--header "Content-Type: application/json" \
	--url "${BASE}${REST_CONTEXT_PATH}" \
	--data '{"title": "First entry"}'
```

List or count entries with a `GET` on the same path; `totalCount` reports the size.

## Deletion (Cleanup)

A definition bound by inheritance refuses deletion with *"you must first disable inheritance and delete its relationships."* Disabling inheritance is a **`PUT`** on the relationship with `edge: false` (a `PATCH` returns `405`); the relationship can then be deleted, and finally the definitions (children before the parent).

```bash
curl --silent --request PUT --user "${AUTH}" \
	--header "Content-Type: application/json" \
	--url "${ADMIN}/object-relationships/${RELATIONSHIP_ID}" \
	--data '{"deletionType": "cascade", "edge": false, "label": {"en_US": "x"}, "name": "x", "type": "oneToMany"}'

curl --silent --request DELETE --user "${AUTH}" \
	--url "${ADMIN}/object-relationships/${RELATIONSHIP_ID}"

curl --silent --request DELETE --user "${AUTH}" \
	--url "${ADMIN}/object-definitions/${CHILD_ID}"
```
