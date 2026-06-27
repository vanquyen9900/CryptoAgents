def get_prompt_patch(prompt_set: dict, role: str) -> str:
    """
    Returns the role-specific prompt patch instruction.
    If 'all' exists, it is included. If the specific 'role' exists, it is appended.
    The output is formatted as an additional instruction block.
    """
    if not prompt_set or "role_patches" not in prompt_set:
        return ""

    patches = prompt_set["role_patches"]
    if not patches:
        return ""

    patch_lines = []

    # Apply global 'all' patch first if it exists
    if "all" in patches and patches["all"].strip():
        patch_lines.append(patches["all"].strip())

    # Apply role-specific patch
    if role in patches and patches[role].strip():
        patch_lines.append(patches[role].strip())

    if not patch_lines:
        return ""

    combined_patch = "\n\n".join(patch_lines)

    formatted_patch = (
        "\n\n"
        "============================================================\n"
        "ADDITIONAL TOURNAMENT INSTRUCTIONS FOR THIS RUN:\n"
        "============================================================\n"
        f"{combined_patch}\n"
        "============================================================\n"
    )

    return formatted_patch
