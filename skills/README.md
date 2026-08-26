# Local Skills

HakusAgent does not ship a workspace Skill catalog in this directory. Skills
are user-managed so the application stays small and the repository language
statistics reflect product code instead of optional Skill assets.

## Install

The desktop app can install and manage Skills from **Settings > Skills**. It
accepts a local Skill directory, `github:owner/repository`, or an HTTP(S) ZIP or
TAR archive that contains one `SKILL.md`.

HakusCLI users can also run:

```text
/skills install <source>
```

## Discovery Locations

HakusAgent looks for Skills in these locations, in priority order:

1. `<project>/.hakus/skills/`
2. `<project>/.agents/skills/`
3. `~/.hakus/skills/`
4. `~/.agents/skills/`

HakusCLI additionally supports this flat `skills/` directory for compatibility.
Local content placed here is ignored by Git and is not distributed with the
repository.

Each Skill must have its own directory and a `SKILL.md` file:

```text
skills/
└── my-skill/
    ├── SKILL.md
    ├── scripts/
    └── references/
```

In the desktop chat composer, type `@` and select an enabled Skill to attach it
to the current request.
