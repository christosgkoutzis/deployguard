#!/usr/bin/env python3
import os
import sys
import yaml
import glob
import subprocess
from collections import defaultdict

def represent_str(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)
yaml.add_representer(str, represent_str)

def load_topology(path):
    with open(path, 'r') as f:
        content = f.read()
        import string
        template = string.Template(content)
        try:
            content = template.safe_substitute(os.environ)
        except Exception:
            pass
        return yaml.safe_load(content)

def build_graph(services):
    graph = defaultdict(list)
    for svc in services:
        for dep in svc.get('depends_on', []):
            graph[svc['name']].append(dep)
    return graph

def resolve_focus(graph, focus_node, all_services, all_deps, all_mocks):
    resolved = set()
    queue = [focus_node]
    while queue:
        curr = queue.pop(0)
        if curr not in resolved:
            resolved.add(curr)
            queue.extend(graph[curr])
    
    services = [s for s in all_services if s['name'] in resolved]
    deps = [d for d in all_deps if d['name'] in resolved]
    mocks = [m for m in all_mocks if m in resolved]
    return services, deps, mocks

def create_argocd_app(name, chart, repo_url, values, namespace="deployguard"):
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {
            "annotations": {"argocd.argoproj.io/sync-wave": str(values.pop("syncWave", "3"))},
            "name": name,
            "namespace": "argocd"
        },
        "spec": {
            "project": "default",
            "source": {
                "repoURL": repo_url,
                "chart": chart,
                "targetRevision": "0.1.0",
                "helm": {
                    "releaseName": name,
                    "values": yaml.dump(values, default_flow_style=False)
                }
            },
            "destination": {
                "server": "https://kubernetes.default.svc",
                "namespace": namespace
            },
            "syncPolicy": {
                "syncOptions": ["CreateNamespace=true"]
            }
        }
    }

def generate_gitops_manifests(topology, focus=None):
    os.makedirs("platform/gitops", exist_ok=True)
    for f in glob.glob("platform/gitops/*.yaml"):
        os.remove(f)

    all_services = topology.get('services', [])
    all_deps = topology.get('dependencies', [])
    all_mocks = topology.get('mocks', [])
    
    if focus:
        graph = build_graph(all_services)
        services, deps, mocks = resolve_focus(graph, focus, all_services, all_deps, all_mocks)
    else:
        services, deps, mocks = all_services, all_deps, all_mocks

    cluster_domain = os.environ.get("CLUSTER_DOMAIN", "127.0.0.1.nip.io")
    local_registry = os.environ.get("LOCAL_REGISTRY", "http://host.k3d.internal:8081")

    # Write .sync-env.env for verify.sh
    with open(".sync-env.env", "w") as f:
        f.write(f"export SERVICES=\"{','.join(s['name'] for s in services)}\"\n")
        f.write(f"export MOCKS=\"{','.join(mocks)}\"\n")
        f.write(f"export EXTERNAL_DEPS=\"{','.join(d['name'] for d in deps)},platform-seeds\"\n")
    # 1. Dependencies
    for dep in deps:
        version = dep.get('version', '*')
        
        params = [{"name": s.split('=', 1)[0], "value": s.split('=', 1)[1]} for s in dep.get('set', [])]
        
        app = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "Application",
            "metadata": {
            "name": dep['name'], "namespace": "argocd", "annotations": {"argocd.argoproj.io/sync-wave": "1"}
        },
            "spec": {
                "project": "default",
                "source": {
                    "repoURL": dep['repo'].replace("${LOCAL_REGISTRY}", local_registry),
                    "chart": dep['chart'],
                    "targetRevision": version,
                    "helm": {
                        "releaseName": dep['name']
                    }
                },
                "destination": {
                    "server": "https://kubernetes.default.svc",
                    "namespace": "deployguard"
                },
                "syncPolicy": {"syncOptions": ["CreateNamespace=true"]}
            }
        }
        if params:
            app['spec']['source']['helm']['parameters'] = params

        with open(f"platform/gitops/{dep['name']}.yaml", "w") as f:
            yaml.dump(app, f, default_flow_style=False)

    # 2. Platform Seeds
    if os.path.exists("seeds") and os.listdir("seeds"):
        seeds_vals = {"seeds": {}, "syncWave": "2", "env": {}}
        for seed_file in os.listdir("seeds"):
            if os.path.isfile(f"seeds/{seed_file}"):
                with open(f"seeds/{seed_file}", "r") as sf:
                    seeds_vals["seeds"][seed_file] = sf.read()
        app = create_argocd_app("platform-seeds", "platform-seeds", local_registry, seeds_vals)
        with open("platform/gitops/platform-seeds.yaml", "w") as f:
            yaml.dump(app, f, default_flow_style=False)

    # 3. Mocks
    for mock_name in mocks:
        mock_dir = f"mocks/{mock_name}"
        mock_vals = {"clusterDomain": cluster_domain, "mocks": {}}
        if os.path.exists(mock_dir):
            for mfile in os.listdir(mock_dir):
                if mfile.endswith('.json'):
                    with open(f"{mock_dir}/{mfile}", "r") as mf:
                        mock_vals["mocks"][mfile] = mf.read()
        app = create_argocd_app(mock_name, "wiremock", local_registry, mock_vals)
        with open(f"platform/gitops/{mock_name}.yaml", "w") as f:
            yaml.dump(app, f, default_flow_style=False)

    # 4. Services
    for svc in services:
        chart_name = svc.get('type', 'webservice')
        vals = {
            "image": {
                "repository": svc['name'],
                "tag": "v1"
            },
            "persistence": {
                "enabled": False
            },
            "externalSecret": {
                "enabled": True,
                "vaultPath": f"deployguard/{svc['name']}"
            }
        }
        
        if chart_name not in ['worker', 'test']:
            vals["service"] = {
                "port": 80,
                "targetPort": svc.get('port', 8000)
            }
            vals["ingress"] = {
                "host": f"{svc['name']}.{cluster_domain}"
            }
            vals["health"] = {
                "path": svc.get("health_endpoint", "/health")
            }
            
        vals["env"] = {}
        vals["resources"] = svc.get('resources', {})
        

        env_file = svc.get('env_file')
        if env_file:
            path = svc.get('build_path', f"services/{svc['name']}")
            try:
                with open(f"{path}/{env_file}", 'r') as ef:
                    for eline in ef:
                        if '=' in eline and not eline.startswith('#'):
                            k, v = eline.strip().split('=', 1)
                            vals['env'][k] = v
            except: pass
        for kv in svc.get('env', []):
            if '=' in kv:
                k, v = kv.split('=', 1)
                if k == "INIT_COMMAND":
                    vals['initCommand'] = v
                else:
                    vals['env'][k] = v

        app = create_argocd_app(svc['name'], chart_name, local_registry, vals)
        with open(f"platform/gitops/{svc['name']}.yaml", "w") as f:
            yaml.dump(app, f, default_flow_style=False)

    print("GitOps manifests generated successfully.")

if __name__ == "__main__":
    focus = None
    if len(sys.argv) > 1 and sys.argv[1] == "--focus":
        focus = sys.argv[2]
    
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k] = v

    topology = load_topology("deployguard.yaml")
    generate_gitops_manifests(topology, focus)
