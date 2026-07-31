import sys, json
def main():
    try:
        data = json.loads(sys.stdin.read())
        csv = data.get("csv_data", "")
        lines = csv.strip().split("\n")
        if not lines:
            print(json.dumps({"records": [], "count": 0}))
            return
        headers = lines[0].split(",")
        records = []
        for line in lines[1:]:
            vals = line.split(",")
            records.append(dict(zip(headers, vals)))
        print(json.dumps({"records": records, "count": len(records)}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
if __name__ == "__main__":
    main()
