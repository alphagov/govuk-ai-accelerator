import os

Cyan = '\033[96m'
Blue = "\033[34m"
Bold = "\033[1m"
Reset = "\033[0m"

def clean_content(output_dir):
    print(Bold + Cyan + "🛀 Cleaning content..." + Reset)
    print("")

    files_cleaned = 0

    output_files = os.listdir(output_dir)

    if output_files:
        count = 0
        for file in output_files:
            count += 1
            progress = " (" + str(count) + "/" + str(len(output_files)) + ") "

            with open(output_dir + "/" + file, 'r') as content:
                lines = content.readlines()

            new_lines = []
            previous_line_blank = False

            for line in lines:
                new_line = line.strip()

                if new_line in {"Print this page", "Printable version"}:
                    continue

                if new_line == "":
                    if not previous_line_blank:
                        new_lines.append(line)
                    previous_line_blank = True
                else:
                    new_lines.append(line.lstrip())
                    previous_line_blank = False

            with open(output_dir + "/" + file, 'w') as content:
                content.writelines(new_lines)
                content.close()
            print("✅" + progress + Blue + Bold + file + Reset + " successfully cleaned")
            files_cleaned += 1

        print("")
        print("🧼 " + str(files_cleaned) + " files cleaned")
    else:
        print("⚠️ No content files found. Check the output directory")