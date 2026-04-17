"""Lightweight parser for Xyce ASCII .prn output files."""


class XycePrnParser:
    """Parse Xyce space-separated .prn files."""

    def __init__(self, path: str):
        self.path = path
        self.columns = []
        self.rows = []

    def parse(self):
        """Parse the file and populate columns / rows."""
        with open(self.path, "r") as f:
            lines = f.readlines()

        if not lines:
            raise ValueError(f"Empty PRN file: {self.path}")

        # First line: column headers
        self.columns = lines[0].strip().split()
        self.rows = []
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) != len(self.columns):
                continue
            self.rows.append([float(p) for p in parts])

    def read_at_time(self, variable_name: str, target_time: float):
        """Return the value of *variable_name* at the row closest to *target_time*."""
        if variable_name not in self.columns:
            raise KeyError(
                f"Variable '{variable_name}' not in PRN. Available: {self.columns}"
            )
        col_idx = self.columns.index(variable_name)
        time_idx = self.columns.index("TIME")

        best_val = None
        best_diff = float("inf")
        for row in self.rows:
            t = row[time_idx]
            diff = abs(t - target_time)
            if diff < best_diff:
                best_diff = diff
                best_val = row[col_idx]
        return best_val

    def read_latest(self, variable_name: str):
        """Return the last available value of *variable_name*."""
        if variable_name not in self.columns:
            raise KeyError(
                f"Variable '{variable_name}' not in PRN. Available: {self.columns}"
            )
        col_idx = self.columns.index(variable_name)
        if not self.rows:
            raise ValueError("No data rows in PRN file")
        return self.rows[-1][col_idx]
