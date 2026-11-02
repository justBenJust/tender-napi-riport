"""Package allowlisted code/docs, excluding exports and generated reports."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    files = [ROOT/'SKILL.md', ROOT/'README.md', ROOT/'LICENSE', ROOT/'VERSION', ROOT/'requirements.txt']
    files += [path for path in sorted((ROOT/'scripts').glob('*.py')) if path.name!='build_skill.py']
    files += [ROOT/'references'/name for name in ('company_profile.md', 'evaluation_rules.md',
              'column_aliases.example.json','manual_sources.md','ted_web_prompt.md','outlook_source.md','browser_source.md')]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'tender-napi-riport/' + path.relative_to(ROOT).as_posix())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(ROOT/'dist/tender-napi-riport.zip'))
    print(build(parser.parse_args().out))
