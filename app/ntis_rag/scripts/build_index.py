"""Build NTIS indexes from the configured spreadsheet."""

def main():
    from ..indexing.build_index import main as build
    build()

if __name__ == "__main__":
    main()
