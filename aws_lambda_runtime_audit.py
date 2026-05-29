#!/usr/bin/env python3

"""
AWS Lambda Runtime Audit

Audits Lambda functions for deprecated runtimes across one or more AWS regions.

Example:
    python lambda_runtime_audit.py --regions eu-west-1 eu-west-2 --runtime python3.10
    python lambda_runtime_audit.py --regions eu-west-1 --runtime python3.10 --exclude custodian
"""

import argparse
import csv
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List

import boto3
from botocore.exceptions import ClientError, BotoCoreError


@dataclass
class LambdaFinding:
    region: str
    function_name: str
    arn: str
    runtime: str
    last_modified: str
    time_since_modified: str


def years_months_since(date: datetime) -> str:
    now = datetime.now(date.tzinfo)

    years = now.year - date.year
    months = now.month - date.month

    if months < 0:
        years -= 1
        months += 12

    if months == 0 and now.day < date.day:
        years -= 1
        months = 11

    if years or months:
        return f"{years} years {months} months"

    return "Less than a month ago"


def parse_last_modified(value: str) -> datetime:
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    raise ValueError(f"Unsupported LastModified format: {value}")


def list_lambda_functions(region: str) -> List[dict]:
    client = boto3.client("lambda", region_name=region)
    paginator = client.get_paginator("list_functions")

    functions = []

    for page in paginator.paginate(FunctionVersion="ALL"):
        functions.extend(page.get("Functions", []))

    return functions


def audit_region(region: str, runtime: str, exclude_terms: List[str]) -> List[LambdaFinding]:
    findings = []
    exclude_terms = [term.lower() for term in exclude_terms]

    try:
        functions = list_lambda_functions(region)

        for function in functions:
            function_name = function.get("FunctionName", "")
            function_runtime = function.get("Runtime", "unknown")

            if any(term in function_name.lower() for term in exclude_terms):
                continue

            if function_runtime != runtime:
                continue

            last_modified_raw = function.get("LastModified")
            last_modified_date = parse_last_modified(last_modified_raw)

            findings.append(
                LambdaFinding(
                    region=region,
                    function_name=function_name,
                    arn=function.get("FunctionArn", ""),
                    runtime=function_runtime,
                    last_modified=last_modified_date.strftime("%Y-%m-%d"),
                    time_since_modified=years_months_since(last_modified_date),
                )
            )

    except (ClientError, BotoCoreError, ValueError) as error:
        print(f"[WARN] Failed to audit region {region}: {error}")

    return findings


def print_findings(findings: List[LambdaFinding]) -> None:
    if not findings:
        print("No matching Lambda functions found.")
        return

    for finding in findings:
        print("-" * 80)
        print(f"Region:                  {finding.region}")
        print(f"Function Name:           {finding.function_name}")
        print(f"ARN:                     {finding.arn}")
        print(f"Runtime:                 {finding.runtime}")
        print(f"Last Modified:           {finding.last_modified}")
        print(f"Time Since Modified:     {finding.time_since_modified}")

    print("-" * 80)
    print(f"Total matching functions: {len(findings)}")


def export_csv(findings: List[LambdaFinding], output_file: str) -> None:
    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=asdict(findings[0]).keys())
        writer.writeheader()

        for finding in findings:
            writer.writerow(asdict(finding))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit AWS Lambda functions for deprecated runtimes."
    )

    parser.add_argument(
        "--regions",
        nargs="+",
        default=["eu-west-1"],
        help="AWS regions to scan. Default: eu-west-1",
    )

    parser.add_argument(
        "--runtime",
        default="python3.10",
        help="Runtime to audit. Default: python3.10",
    )

    parser.add_argument(
        "--exclude",
        nargs="*",
        default=["custodian"],
        help="Function name terms to exclude. Default: custodian",
    )

    parser.add_argument(
        "--csv",
        help="Optional path to export findings as CSV.",
    )

    args = parser.parse_args()

    all_findings = []

    for region in args.regions:
        print(f"Scanning region: {region}")
        findings = audit_region(region, args.runtime, args.exclude)
        all_findings.extend(findings)

    print_findings(all_findings)

    if args.csv and all_findings:
        export_csv(all_findings, args.csv)
        print(f"CSV exported to: {args.csv}")


if __name__ == "__main__":
    main()