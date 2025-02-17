const fs = require("fs");
const path = require("path");

// 入力ディレクトリを指定
const inputDir = "/Users/hayakawa/Library/Mobile Documents/com~apple~CloudDocs/ma-jan/tenhou_db_test";

// 入力ディレクトリが存在するか確認
if (!fs.existsSync(inputDir)) {
    console.error(`エラー: 入力ディレクトリ "${inputDir}" が存在しません。`);
    process.exit(1);
}

// ディレクトリ内のXMLファイルを取得
const files = fs.readdirSync(inputDir).filter(file => file.endsWith(".xml"));

if (files.length === 0) {
    console.log("指定されたディレクトリにXMLファイルがありません。");
    process.exit(0);
}

// 牌譜IDを抜き出す正規表現
const haifuIdRegex = /<mjloggm.*id="(.*?)"/;

// XMLファイルを順に処理
files.forEach(file => {
    const filePath = path.join(inputDir, file);

    try {
        // ファイル内容を読み込む
        const content = fs.readFileSync(filePath, "utf-8");

        // 牌譜IDを抽出
        const match = content.match(haifuIdRegex);
        if (match && match[1]) {
            console.log(`ファイル: ${file}, 牌譜ID: ${match[1]}`);
        } else {
            console.warn(`ファイル: ${file}, 牌譜IDが見つかりませんでした。`);
        }
    } catch (error) {
        console.error(`エラー: ファイル "${file}" の読み込みに失敗しました。\n`, error);
    }
});
