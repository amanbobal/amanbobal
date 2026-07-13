import datetime
import hashlib
import os
import sys
import time

def load_env():
    paths = [
        os.path.join("..", ".env.local"),
        os.path.join("..", ".env"),
        ".env.local",
        ".env"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            os.environ[key] = val
                print(f"Loaded environment variables from {path}")
                break
            except Exception as e:
                print(f"Warning: failed to load {path}: {e}")

load_env()


import requests
from dateutil import relativedelta
from lxml import etree

import profile_config


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "").strip() or None
USER_NAME = os.environ.get("USER_NAME", "amanbobal").strip()
HEADERS = {"authorization": f"token {ACCESS_TOKEN}"} if ACCESS_TOKEN else {}
QUERY_COUNT = {
    "user_getter": 0,
    "follower_getter": 0,
    "graph_repos_stars": 0,
    "recursive_loc": 0,
    "graph_commits": 0,
    "loc_query": 0,
}

OWNER_ID = None


def daily_readme(birthday):
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return "{} {}, {} {}, {} {}{}".format(
        diff.years,
        "year" + format_plural(diff.years),
        diff.months,
        "month" + format_plural(diff.months),
        diff.days,
        "day" + format_plural(diff.days),
        " 🎂" if (diff.months == 0 and diff.days == 0) else "",
    )


def format_plural(unit):
    return "s" if unit != 1 else ""


def simple_request(func_name, query, variables):
    request = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
    )
    if request.status_code == 200:
        return request
    raise Exception(func_name, " has failed with a", request.status_code, request.text, QUERY_COUNT)


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    query_count("graph_repos_stars")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }"""
    variables = {"owner_affiliation": owner_affiliation, "login": USER_NAME, "cursor": cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if count_type == "repos":
        return request.json()["data"]["user"]["repositories"]["totalCount"]
    if count_type == "stars":
        return stars_counter(request.json()["data"]["user"]["repositories"]["edges"])


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    query_count("recursive_loc")
    query = """
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }"""
    variables = {"repo_name": repo_name, "owner": owner, "cursor": cursor}
    request = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
    )
    if request.status_code == 200:
        default_branch = request.json()["data"]["repository"]["defaultBranchRef"]
        if default_branch is not None:
            return loc_counter_one_repo(
                owner,
                repo_name,
                data,
                cache_comment,
                default_branch["target"]["history"],
                addition_total,
                deletion_total,
                my_commits,
            )
        return 0
    force_close_file(data, cache_comment)
    if request.status_code == 403:
        raise Exception("Too many requests in a short amount of time!\nYou've hit the non-documented anti-abuse limit!")
    raise Exception("recursive_loc() has failed with a", request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    for node in history["edges"]:
        if node["node"]["author"]["user"] == OWNER_ID:
            my_commits += 1
            addition_total += node["node"]["additions"]
            deletion_total += node["node"]["deletions"]

    if history["edges"] == [] or not history["pageInfo"]["hasNextPage"]:
        return addition_total, deletion_total, my_commits
    return recursive_loc(
        owner,
        repo_name,
        data,
        cache_comment,
        addition_total,
        deletion_total,
        my_commits,
        history["pageInfo"]["endCursor"],
    )


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=[]):
    query_count("loc_query")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }"""
    variables = {"owner_affiliation": owner_affiliation, "login": USER_NAME, "cursor": cursor}
    request = simple_request(loc_query.__name__, query, variables)
    if request.json()["data"]["user"]["repositories"]["pageInfo"]["hasNextPage"]:
        edges += request.json()["data"]["user"]["repositories"]["edges"]
        return loc_query(
            owner_affiliation,
            comment_size,
            force_cache,
            request.json()["data"]["user"]["repositories"]["pageInfo"]["endCursor"],
            edges,
        )
    return cache_builder(edges + request.json()["data"]["user"]["repositories"]["edges"], comment_size, force_cache)


def cache_filename():
    return "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    cached = True
    filename = cache_filename()
    try:
        with open(filename, "r") as f:
            data = f.readlines()
    except FileNotFoundError:
        data = []
        if comment_size > 0:
            for _ in range(comment_size):
                data.append("This line is a comment block. Write whatever you want here.\n")
        with open(filename, "w") as f:
            f.writelines(data)

    if len(data) - comment_size != len(edges) or force_cache:
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, "r") as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]["node"]["nameWithOwner"].encode("utf-8")).hexdigest():
            try:
                if int(commit_count) != edges[index]["node"]["defaultBranchRef"]["target"]["history"]["totalCount"]:
                    owner, repo_name = edges[index]["node"]["nameWithOwner"].split("/")
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = (
                        repo_hash
                        + " "
                        + str(edges[index]["node"]["defaultBranchRef"]["target"]["history"]["totalCount"])
                        + " "
                        + str(loc[2])
                        + " "
                        + str(loc[0])
                        + " "
                        + str(loc[1])
                        + "\n"
                    )
            except TypeError:
                data[index] = repo_hash + " 0 0 0 0\n"
    with open(filename, "w") as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges, filename, comment_size):
    with open(filename, "r") as f:
        data = []
        if comment_size > 0:
            data = f.readlines()[:comment_size]
    with open(filename, "w") as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node["node"]["nameWithOwner"].encode("utf-8")).hexdigest() + " 0 0 0 0\n")


def force_close_file(data, cache_comment):
    filename = cache_filename()
    with open(filename, "w") as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print("There was an error while writing to the cache file. Partial data saved to", filename)


def stars_counter(data):
    total_stars = 0
    for node in data:
        total_stars += node["node"]["stargazers"]["totalCount"]
    return total_stars


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def justify_format(root, element_id, new_text, length=0):
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: "", 1: " ", 2: ". "}
        dot_string = dot_map[just_len]
    else:
        dot_string = " " + ("." * just_len) + " "
    find_and_replace(root, f"{element_id}_dots", dot_string)


def justify_field(root, element_id, new_text, key_name, align_column):
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)

    # Calculate number of dots required for alignment to align_column
    # TargetTotal = align_column = 68
    # just_len = 63 - len(Key) - len(Value)
    # where 63 comes from (TargetTotal - 5)
    just_len = max(2, align_column - len(key_name) - len(new_text) - 5)

    dot_string = " " + ("." * just_len) + " "
    find_and_replace(root, f"{element_id}_dots", dot_string)


def process_profile_image():
    extensions = [".png", ".jpg", ".jpeg"]
    img_path = None
    for ext in extensions:
        test_path = os.path.join("assets", f"profile{ext}")
        if os.path.exists(test_path):
            img_path = test_path
            break

    if not img_path:
        return

    # Calculate hash of the image
    hasher = hashlib.sha256()
    with open(img_path, "rb") as f:
        hasher.update(f.read())
    img_hash = hasher.hexdigest()

    hash_file = os.path.join("cache", "profile_image_hash.txt")
    cached_hash = ""
    if os.path.exists(hash_file):
        with open(hash_file, "r") as f:
            cached_hash = f.read().strip()

    if img_hash == cached_hash:
        print("Profile image has not changed. Skipping image processing.")
        return

    print(f"New profile image detected: {img_path}. Processing...")

    try:
        from PIL import Image
    except ImportError:
        print("PIL/Pillow is not installed. Please run 'pip install Pillow' to support profile image conversion.")
        return

    img = Image.open(img_path)

    # Maintain portrait aspect ratio of 350:480 or fit it within 500x685
    img.thumbnail((500, 685), Image.Resampling.LANCZOS)

    # Convert to palette mode (adaptive, 256 colors) for size optimization
    img_p = img.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)

    out_path = os.path.join("assets", "ascii-magic-500-p.png")
    img_p.save(out_path, "PNG", optimize=True)

    # Save the new hash
    os.makedirs(os.path.dirname(hash_file), exist_ok=True)
    with open(hash_file, "w") as f:
        f.write(img_hash)

    print(f"Profile image processed and saved to {out_path} (size: {os.path.getsize(out_path)} bytes)")


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data):
    tree = etree.parse(filename)
    root = tree.getroot()

    # 1. Update static fields (and justify them)
    static_fields = {
        "header_data": profile_config.HEADER,
        "os_data": profile_config.OS,
        "host_data": profile_config.HOST,
        "kernel_data": profile_config.KERNEL,
        "ide_data": profile_config.IDE,
        "lang_prog_data": profile_config.LANGUAGES_PROGRAMMING,
        "lang_comp_data": profile_config.LANGUAGES_COMPUTER,
        "lang_real_data": profile_config.LANGUAGES_REAL,
        "hobbies_data": profile_config.HOBBIES,
        "email_personal_data": profile_config.CONTACT["email_personal"],
        "email_work_data": profile_config.CONTACT["email_work"],
        "linkedin_data": profile_config.CONTACT["linkedin"],
        "discord_data": profile_config.CONTACT["discord"],
        "website_data": profile_config.CONTACT["website"],
    }

    ALIGN_COLUMN = 68
    field_keys = {
        "os_data": "OS",
        "host_data": "Host",
        "kernel_data": "Kernel",
        "ide_data": "IDE",
        "lang_prog_data": "Languages.Programming",
        "lang_comp_data": "Languages.Computer",
        "lang_real_data": "Languages.Real",
        "hobbies_data": "Hobbies",
        "email_personal_data": "Email.Personal",
        "email_work_data": "Email.Work",
        "website_data": "Website",
        "linkedin_data": "LinkedIn",
        "discord_data": "Discord",
    }

    for element_id, value in static_fields.items():
        if element_id == "header_data":
            find_and_replace(root, element_id, value)
        else:
            key_name = field_keys.get(element_id)
            justify_field(root, element_id, value, key_name, ALIGN_COLUMN)

    # 2. Update dynamic fields (and justify Uptime)
    justify_field(root, "age_data", age_data, "Uptime", ALIGN_COLUMN)
    justify_format(root, "commit_data", commit_data, 22)
    justify_format(root, "star_data", star_data, 14)
    justify_format(root, "repo_data", repo_data, 6)
    justify_format(root, "contrib_data", contrib_data)
    justify_format(root, "follower_data", follower_data, 10)
    justify_format(root, "loc_data", loc_data[2], 9)
    justify_format(root, "loc_add", loc_data[0])
    justify_format(root, "loc_del", loc_data[1], 7)

    # 3. Embed the base64 image data URI of assets/ascii-magic-500-p.png
    import base64
    img_path = os.path.join("assets", "ascii-magic-500-p.png")
    if os.path.exists(img_path):
        try:
            with open(img_path, "rb") as f:
                img_data = f.read()
            base64_str = base64.b64encode(img_data).decode("utf-8")
            data_uri = f"data:image/png;base64,{base64_str}"

            image_elements = root.xpath(".//*[local-name()='image']")
            if len(image_elements) > 0:
                image_elements[0].set("{http://www.w3.org/1999/xlink}href", data_uri)
        except Exception as e:
            print(f"Error embedding image in {filename}: {e}")

    tree.write(filename, encoding="utf-8", xml_declaration=True)


def commit_counter(comment_size):
    total_commits = 0
    filename = cache_filename()
    with open(filename, "r") as f:
        data = f.readlines()
    data = data[comment_size:]
    for line in data:
        total_commits += int(line.split()[2])
    return total_commits


def user_getter(username):
    query_count("user_getter")
    query = """
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }"""
    variables = {"login": username}
    request = simple_request(user_getter.__name__, query, variables)
    return {"id": request.json()["data"]["user"]["id"]}, request.json()["data"]["user"]["createdAt"]


def follower_getter(username):
    query_count("follower_getter")
    query = """
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }"""
    request = simple_request(follower_getter.__name__, query, {"login": username})
    return int(request.json()["data"]["user"]["followers"]["totalCount"])


def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference):
    print("{:<23}".format("   " + query_type + ":"), sep="", end="")
    if difference > 1:
        print("{:>12}".format("%.4f" % difference + " s "))
    else:
        print("{:>12}".format("%.4f" % (difference * 1000) + " ms"))


if __name__ == "__main__":
    # Process profile image first if one has been uploaded
    process_profile_image()

    print("Calculation times:")
    
    if ACCESS_TOKEN:
        user_data, user_time = perf_counter(user_getter, USER_NAME)
        globals()["OWNER_ID"] = user_data[0]
        formatter("account data", user_time)

        age_data, age_time = perf_counter(daily_readme, profile_config.BIRTHDAY)
        formatter("age calculation", age_time)

        comment_size = profile_config.CACHE_COMMENT_SIZE
        total_loc, loc_time = perf_counter(loc_query, ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"], comment_size)
        formatter("LOC (cached)" if total_loc[-1] else "LOC (no cache)", loc_time)

        commit_data, commit_time = perf_counter(commit_counter, comment_size)
        star_data, star_time = perf_counter(graph_repos_stars, "stars", ["OWNER"])
        repo_data, repo_time = perf_counter(graph_repos_stars, "repos", ["OWNER"])
        contrib_data, contrib_time = perf_counter(graph_repos_stars, "repos", ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"])
        follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

        formatted_loc = ["{:,}".format(total_loc[index]) for index in range(len(total_loc) - 1)]
        
        total_time = user_time + age_time + loc_time + commit_time + star_time + repo_time + contrib_time
    else:
        print("ACCESS_TOKEN is missing. Running in local/offline mode.")
        age_data = daily_readme(profile_config.BIRTHDAY)
        commit_data = 0
        try:
            commit_data = commit_counter(profile_config.CACHE_COMMENT_SIZE)
        except Exception:
            pass
        star_data = 0
        repo_data = 0
        contrib_data = 0
        follower_data = 0
        formatted_loc = ["0", "0", "0"]
        total_time = 0

    svg_overwrite(
        "dark_mode.svg",
        age_data,
        commit_data,
        star_data,
        repo_data,
        contrib_data,
        follower_data,
        formatted_loc,
    )
    svg_overwrite(
        "light_mode.svg",
        age_data,
        commit_data,
        star_data,
        repo_data,
        contrib_data,
        follower_data,
        formatted_loc,
    )

    if ACCESS_TOKEN:
        print(
            "\033[F\033[F\033[F\033[F\033[F\033[F\033[F\033[F",
            "{:<21}".format("Total function time:"),
            "{:>11}".format("%.4f" % total_time),
            " s \033[E\033[E\033[E\033[E\033[E\033[E\033[E\033[E",
            sep="",
        )
        print("Total GitHub GraphQL API calls:", "{:>3}".format(sum(QUERY_COUNT.values())))
