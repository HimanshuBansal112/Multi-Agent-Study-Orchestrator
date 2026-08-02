import json
import random

path = str((Path(__file__).parent / "..").resolve())
path = os.path.join(path, "DataBase")
quiz_path = os.path.join(path, "form.json")


def load():
    with open(quiz_path, "r") as f:
        data = json.load(f)
    return data


def save(data):
    with open(quiz_path, "w") as f:
        json.dump(data, f, indent=2)


data = load()
size = len(data["data"])

data["data"][1:] = random.sample(data["data"][1:], len(data["data"]) - 1)

assert len(data["data"]) == size, "Size should be consistent before and after update"

for i in range(1, size):
    data["data"][i]["createItem"]["location"]["index"] = i - 1

save(data)
