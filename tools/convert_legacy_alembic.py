"""Stage lossless HDF5 -> Ogawa conversions, validate, then publish explicitly.

Uses Houdini's official abcconvert/abcecho, not a scene re-export. Publishing
retains an exact .abc.hdf5.bak beside every source. Never overwrites a backup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HDF5 = b"\x89HDF\r\n\x1a\n"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def header(path):
    with path.open("rb") as stream:
        return stream.read(8)


def run(args, timeout=600):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(result.stdout.decode("utf-8", errors="replace")[-4000:])
    return result.stdout


def structure(output):
    # The converter necessarily updates the archive's Alembic library version.
    # All other metadata and object/property inventory must remain identical.
    return [line for line in output.splitlines() if not line.strip().startswith(b"using Alembic :")]


def stage(root, houdini, blender, staging_dir=None):
    root = root.resolve(strict=True)
    if staging_dir is None:
        staging = Path(tempfile.mkdtemp(prefix="pipe_alembic_ogawa_"))
    else:
        staging = staging_dir.resolve()
        staging.mkdir(parents=True, exist_ok=False)
    manifest = {"root": str(root), "staging": str(staging), "files": []}
    manifest_path = staging / "manifest.json"
    validator = Path(__file__).with_name("validate_alembic_blender.py").resolve()
    for source in sorted(root.rglob("*.abc")):
        if header(source) != HDF5:
            continue
        index = len(manifest["files"])
        target = staging / f"{index:03d}_{source.name}"
        item = {"source": str(source), "converted": str(target),
                "source_sha256": digest(source), "source_size": source.stat().st_size,
                "source_mtime_ns": source.stat().st_mtime_ns, "status": "pending"}
        manifest["files"].append(item)
        try:
            run([str(houdini / "abcconvert.exe"), "-toOgawa", str(source), str(target)])
            if header(target)[:5] != b"Ogawa":
                raise RuntimeError("Converted archive is not Ogawa")
            # Compare full object/property inventory, data types, array sizes,
            # sample counts and archive metadata before accepting the conversion.
            original_structure = run([str(houdini / "abcecho.exe"), str(source)])
            converted_structure = run([str(houdini / "abcecho.exe"), str(target)])
            if structure(original_structure) != structure(converted_structure):
                (staging / f"{index:03d}_original.txt").write_bytes(original_structure)
                (staging / f"{index:03d}_converted.txt").write_bytes(converted_structure)
                raise RuntimeError("Archive structure changed during conversion")
            validation = staging / f"{index:03d}_blender.json"
            output = run([str(blender), "--background", "--factory-startup", "--python-exit-code", "1",
                          "--python", str(validator), "--", str(target), str(validation)])
            (staging / f"{index:03d}_blender.log").write_bytes(output)
            item["blender"] = json.loads(validation.read_text(encoding="utf-8"))
            item["converted_sha256"] = digest(target)
            item["converted_size"] = target.stat().st_size
            item["status"] = "validated"
        except Exception as error:
            item["status"] = "failed"
            item["error"] = str(error)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(item), flush=True)
    print("MANIFEST=" + str(manifest_path), flush=True)


def publish(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(manifest["root"]).resolve(strict=True)
    staging = Path(manifest["staging"]).resolve(strict=True)
    for item in manifest["files"]:
        if item["status"] != "validated":
            continue
        source = Path(item["source"]).resolve(strict=True)
        converted = Path(item["converted"]).resolve(strict=True)
        if not source.is_relative_to(root) or not converted.is_relative_to(staging):
            raise RuntimeError("Manifest target outside validated directories")
        if header(source) != HDF5 or digest(source) != item["source_sha256"]:
            raise RuntimeError(f"Source changed since validation: {source}")
        if digest(converted) != item["converted_sha256"]:
            raise RuntimeError(f"Converted file changed: {converted}")
        backup = source.with_name(source.name + ".hdf5.bak")
        if backup.exists():
            raise RuntimeError(f"Backup already exists, refusing to overwrite: {backup}")
        # Exclusive backup creation and verified bytes before touching the source.
        with source.open("rb") as reader, backup.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, backup)
        if digest(backup) != item["source_sha256"]:
            raise RuntimeError(f"Backup verification failed: {backup}")
        candidate = source.with_name(source.name + ".ogawa.pending")
        with converted.open("rb") as reader, candidate.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        if digest(candidate) != item["converted_sha256"]:
            raise RuntimeError(f"Publish verification failed: {candidate}")
        if digest(source) != item["source_sha256"]:
            raise RuntimeError(f"Source changed during backup: {source}")
        os.replace(candidate, source)
        item.update(status="published", backup=str(backup), published_mtime_ns=source.stat().st_mtime_ns)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("PUBLISHED " + str(source), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(r"F:\PIPELINE"))
    parser.add_argument("--houdini-bin", type=Path, default=Path(r"C:\Program Files\Side Effects Software\Houdini 21.0.440\bin"))
    parser.add_argument("--blender", type=Path, default=Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
    parser.add_argument("--publish", type=Path, help="Explicitly publish a validated manifest")
    parser.add_argument("--staging-dir", type=Path, help="New directory for converted files and audit report")
    options = parser.parse_args()
    if options.publish:
        publish(options.publish.resolve(strict=True))
    else:
        stage(options.root, options.houdini_bin, options.blender, options.staging_dir)
