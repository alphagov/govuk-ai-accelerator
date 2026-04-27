from typing import Any

import boto3
import botocore
from flask import render_template, request

from src.web_browser.s3 import parse_responses, list_objects


def index() -> str:
    s3 = boto3.resource("s3")
    all_buckets = s3.buckets.all()
    return render_template("index.html", buckets=all_buckets.all())

def get_bucket_tree_nodes(bucket_name: str, prefix: str) -> list[dict]:
    """Fetch subdirectories (prefixes) for a given S3 path to populate a UI tree."""
    s3_client = boto3.client("s3")
    nodes = []
    try:
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            Delimiter="/"
        )
        for common_prefix in response.get("CommonPrefixes", []):
            full_path = common_prefix["Prefix"]
            # Extract just the folder name
            folder_name = full_path.rstrip('/').split('/')[-1]
            nodes.append({
                "name": folder_name,
                "path": full_path,
                "type": "folder"
            })
    except botocore.exceptions.ClientError as e:
        print(f"Error fetching tree nodes: {e}")
    return nodes


def get_domain_list(bucket_name: str, ) -> list[Any] | None:
    s3_client = boto3.client("s3")
    paginator = s3_client.get_paginator("list_objects_v2")

    try:

        page_iterator = paginator.paginate(Bucket=bucket_name, Delimiter="/")

        top_level_dirs = []

        for page in page_iterator:
            if 'CommonPrefixes' in page:
                for prefix_dict in page["CommonPrefixes"]:
                    top_level_dirs.append(prefix_dict["Prefix"].rstrip('/'))

        return top_level_dirs

    except Exception as e:
        print(f"Error fetching domain list: {e}")


def view_bucket(bucket_name: str, path: str, page: int):
    items_per_page = 500

    s3_client = boto3.client("s3")

    paginator = s3_client.get_paginator("list_objects_v2")
    total_objects = 0
    for page_iterator in paginator.paginate(Bucket=bucket_name, Prefix=path, Delimiter="/"):
        if "CommonPrefixes" in page_iterator:
            total_objects += len(page_iterator["CommonPrefixes"])
        if "Contents" in page_iterator:
            total_objects += sum(1 for obj in page_iterator["Contents"] if not obj["Key"].endswith("/"))

    total_pages = (total_objects + items_per_page - 1) // items_per_page

    try:
        continuation_token = None
        if page > 1:
            temp_response = None
            for _ in range(page - 1):
                temp_response = list_objects(
                    s3_client, bucket_name, path, 100, "/", continuation_token
                )
                if not temp_response.get("IsTruncated"):
                    break
                continuation_token = temp_response.get("NextContinuationToken")

        response = list_objects(s3_client, bucket_name, path, 100, "/", continuation_token)
        contents = parse_responses([response], request.args.get("search", ""))

        return render_template(
            "bucket_contents.html",
            contents=contents,
            bucket_name=bucket_name,
            path=path,
            search_param=request.args.get("search", ""),
            current_page=page,
            total_pages=total_pages,
            active_page="explorer"
        )
    except botocore.exceptions.ClientError as e:
        __handle_exception(e)


def __handle_exception(e):
    error = e.response["Error"]["Message"]

    if error == "AccessDenied":
        return render_template(
            "error.html",
            error="You do not have permission to access this bucket.",
        )
    elif error == "NoSuchBucket":
        return render_template("error.html", error="The specified bucket does not exist.")
    else:
        return render_template("error.html", error=f"An unknown error occurred: {e}")