"""Build a reusable PDF search index using the package pipeline."""
import argparse
from ..pipeline import build_index

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir')
    parser.add_argument('--output-dir')
    parser.add_argument('--model-name')
    args = parser.parse_args()
    index = build_index(args.data_dir, args.output_dir, model_name=args.model_name)
    print(f"Indexed {len(index['docs'])} chunks; {len(index['failed_files'])} failed files")

if __name__ == '__main__':
    main()
