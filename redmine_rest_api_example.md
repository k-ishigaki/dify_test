### multiple `project_id`

```shell
curl --globoff 'http://localhost:8081/issues.json?key=e5def6c6e23711ffb127ed4eb734aacab9b14fe2&set_filter=1&f[]=project_id&op[project_id]==&v[project_id][]=1&v[project_id][]=2&f[]=updated_on&op[updated_on]=%3E%3D&v[updated_on][]=2025-10-30T00:00:00Z&status_id=*&sort=updated_on&limit=10' | jq
```
