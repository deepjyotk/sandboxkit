# Demo repositories (published on GitHub)

These folders mirror the public repos used by `POST /sandboxes/from-repo` and
`digital-ocean/test-from-repo.sh`. **Canonical remote:**

| Folder | GitHub |
|--------|--------|
| [sandboxkit-demo-hello](sandboxkit-demo-hello/) | https://github.com/deepjyotk/sandboxkit-demo-hello |
| [sandboxkit-demo-hello-ts](sandboxkit-demo-hello-ts/) | https://github.com/deepjyotk/sandboxkit-demo-hello-ts |

To refresh the remotes after editing files here:

```bash
cd sandboxkit-demo-hello && git add -A && git commit -m "..." && git push
```

Nested `.git/` directories are listed in the parent `.gitignore` so the main
SandboxKit repo does not track them as submodules.
