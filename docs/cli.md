# CLI Reference

The CLI uses Click with Rich terminal output. Install with `pip install -r requirements.txt`, then use `ai-sre` or `python3 -m cli.main`.

## Cluster

```bash
ai-sre cluster scan                          # scan all namespaces
ai-sre cluster scan --namespace production   # scan specific namespace
```

## Incidents

```bash
ai-sre incidents list                        # list all
ai-sre incidents list --severity critical    # filter by severity
ai-sre incidents list --namespace production # filter by namespace
```

## Analyze

```bash
ai-sre incident analyze <incident-id>
ai-sre incident analyze examples/crashloop_missing_secret.json   # from file
```

## Remediation

```bash
ai-sre remediation plan <incident-id>           # show plan
ai-sre remediation execute <incident-id> --dry-run   # simulate
ai-sre remediation execute <incident-id>         # live execution
ai-sre remediation approve <incident-id>         # approve L2 plan
```

## Simulate

```bash
ai-sre simulate --type crashloop     # CrashLoopBackOff (missing secret)
ai-sre simulate --type oomkilled     # OOMKilled
ai-sre simulate --type pending       # Pod Pending (insufficient resources)
ai-sre simulate --type ingress       # Ingress backend missing
ai-sre simulate --type pvc           # PVC mount failure
ai-sre simulate --type crashloop --demo   # fully offline, no API server
```

## Feedback

```bash
ai-sre learn feedback <incident-id> --success --notes "Fixed by adding secret"
ai-sre learn feedback <incident-id> --failure --notes "Fix did not work"
```

## Options

```bash
ai-sre --api-url http://custom:8000 <command>   # custom API URL
```
