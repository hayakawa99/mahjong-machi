const fs = require("fs");
const { exec } = require("child_process");

// クリーンアップ済みの file_test パス
const fileTestPath = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/file_test_cleaned";

// 出力ディレクトリ
const outputDir = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/tenhou_logs";

// 出力ディレクトリを作成
if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
}

// file_test を読み込む
const fileLines = fs.readFileSync(fileTestPath, "utf-8").split("\n").filter(Boolean);

// 各牌譜IDを処理
fileLines.forEach((line, index) => {
    const haifuId = line.replace(".xml", ""); // .xml を除去

    // tenhou-log コマンドを実行
    exec(`tenhou-log ${haifuId} > "${outputDir}/${haifuId}.json"`, (error, stdout, stderr) => {
        if (error) {
            console.error(`エラー: ${haifuId}`, error.message);
            return;
        }
        console.log(`Processed (${index + 1}/${fileLines.length}): ${haifuId}`);
    });
});

console.log("全ての牌譜IDを処理しました。結果は以下に保存されています:");
console.log(outputDir);
