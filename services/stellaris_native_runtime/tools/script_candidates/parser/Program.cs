// Optional offline parsing adapter. No game attachment or script execution.
using System.Collections;
using System.Reflection;
using System.Text;
using System.Text.Json;
using CWTools.Parser;
using Microsoft.FSharp.Reflection;

static class Program
{
    static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    const int MaxDepth = 192;
    const int MaxNodes = 500000;

    sealed record Node(string? Key, string Operator, string? Value, string? ScalarKind,
                       bool Quoted, Node[]? Children, int Line, int Column, int EndLine, int EndColumn);

    static (string Name, object[] Fields) Union(object value)
    {
        Type type = value.GetType();
        while (type.BaseType != null && FSharpType.IsUnion(type.BaseType, null)) type = type.BaseType;
        var result = FSharpValue.GetUnionFields(value, type, null);
        return (result.Item1.Name, result.Item2);
    }

    static int Position(object? value, string name)
    {
        if (value == null) return 0;
        object? result = value.GetType().GetProperty(name)?.GetValue(value);
        return result == null ? 0 : Convert.ToInt32(result);
    }

    static string Op(object value) => Convert.ToInt32(value) switch
    {
        0 => "=", 1 => ">", 2 => "<", 3 => ">=", 4 => "<=", 5 => "!=", 6 => "==", 7 => "?=",
        _ => throw new InvalidDataException("Unknown CWTools operator")
    };

    static string NormalizeOptionalOperator(string text)
    {
        // Stellaris writes "scope? ="; this CWTools release expects "scope ?=".
        // Swap only horizontal whitespace outside strings/comments. Length,
        // newlines and original source positions are preserved. No evaluation.
        var output = text.ToCharArray();
        bool quoted = false, comment = false, escaped = false;
        for (int i = 0; i < text.Length; ++i)
        {
            char c = text[i];
            if (comment) { if (c == '\n') comment = false; continue; }
            if (quoted)
            {
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') quoted = false;
                continue;
            }
            if (c == '#') { comment = true; continue; }
            if (c == '"') { quoted = true; continue; }
            if (c != '?') continue;
            int end = i + 1;
            while (end < text.Length && (text[end] == ' ' || text[end] == '\t')) ++end;
            if (end > i + 1 && end < text.Length && text[end] == '=')
            {
                output[i] = output[end - 1];
                output[end - 1] = '?';
            }
        }
        return new string(output);
    }

    static Node[] Statements(object list, int depth, ref int count, string[] lines)
    {
        if (depth > MaxDepth) throw new InvalidDataException("AST depth limit exceeded");
        var output = new List<Node>();
        foreach (object item in (IEnumerable)list)
        {
            var (name, fields) = Union(item);
            if (name == "CommentStatement") continue;
            if (++count > MaxNodes) throw new InvalidDataException("AST node limit exceeded");
            string? key = null;
            string op = "=";
            bool quotedKey = false;
            object range;
            object value;
            if (name == "KeyValue")
            {
                var (_, positioned) = Union(fields[0]);
                range = positioned[0];
                var (_, pair) = Union(positioned[1]);
                object keyValue = pair[0];
                if (keyValue is not string) keyValue = Union(keyValue).Fields[0];
                key = (string)keyValue; value = pair[1]; op = Op(pair[2]);
                // CWTools 0.6 accepts an adjacent comparator as part of a key.
                // Repair only unquoted keys with the exact comparator suffix.
                int line = Position(range, "StartLine") - 1;
                int column = Position(range, "StartColumn");
                quotedKey = line >= 0 && line < lines.Length && column >= 0 &&
                    column < lines[line].Length && lines[line][column] == '"';
                if (quotedKey && key.StartsWith('"') && key.EndsWith('"')) key = key[1..^1];
                if (!quotedKey && op == "=" && key.Length > 1 && "><!=".Contains(key[^1]))
                {
                    op = key[^1] + "=";
                    key = key[..^1];
                }
            }
            else if (name == "Value") { range = fields[0]; value = fields[1]; }
            else throw new InvalidDataException("Unknown statement " + name);
            var (kind, parts) = Union(value);
            Node[]? children = kind == "Clause" ? Statements(parts[0], depth + 1, ref count, lines) : null;
            string? scalar = children == null
                ? (string?)value.GetType().GetMethod("ToRawString")?.Invoke(value, null)
                : null;
            if (children == null && scalar == null) throw new InvalidDataException("Scalar conversion unavailable");
            output.Add(new Node(key, op, scalar, children == null ? kind : null, kind == "QString", children,
                Position(range, "StartLine"), Position(range, "StartColumn"),
                Position(range, "EndLine"), Position(range, "EndColumn")));
        }
        return output.ToArray();
    }

    static object Parse(string path, string text)
    {
        try
        {
            if (Encoding.UTF8.GetByteCount(text) > 16 * 1024 * 1024)
                throw new InvalidDataException("Document byte limit exceeded");
            var (name, fields) = Union(CKParser.parseString(NormalizeOptionalOperator(text), path));
            if (name != "Success")
                return new { ok = false, path, parser = "CWTools", version = "0.6.0-alpha", error = fields[0].ToString() };
            int count = 0;
            var entries = Statements(fields[0], 0, ref count, text.Split('\n'));
            return new { ok = true, path, parser = "CWTools", version = "0.6.0-alpha", node_count = count, entries };
        }
        catch (Exception error)
        {
            return new { ok = false, path, parser = "CWTools", version = "0.6.0-alpha", error = error.GetType().Name + ": " + error.Message };
        }
    }

    static int Main(string[] args)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        Console.InputEncoding = Encoding.UTF8;
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.SequenceEqual(new[] { "--self-test" }))
        {
            const string fixture = "# scopes are comments\na={ x>=2 x=1.5 v={ a b \"#literal\" } NOT={always=no} }\n";
            string valid = JsonSerializer.Serialize(Parse("fixture.txt", fixture), Json);
            string invalid = JsonSerializer.Serialize(Parse("broken.txt", "a={"), Json);
            Console.WriteLine(valid);
            Console.WriteLine(invalid);
            using var document = JsonDocument.Parse(valid);
            return document.RootElement.GetProperty("ok").GetBoolean() &&
                   document.RootElement.GetProperty("entries")[0].GetProperty("children")[0].GetProperty("operator").GetString() == ">=" &&
                   valid.Contains("\"line\":2") && invalid.Contains("\"ok\":false") ? 0 : 1;
        }
        string? line;
        while ((line = Console.ReadLine()) != null)
        {
            try
            {
                using var request = JsonDocument.Parse(line);
                string path = request.RootElement.GetProperty("path").GetString() ?? "unknown";
                string text = request.RootElement.GetProperty("text").GetString() ?? "";
                Console.WriteLine(JsonSerializer.Serialize(Parse(path, text), Json));
            }
            catch (Exception error)
            {
                Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = error.Message }, Json));
            }
        }
        return 0;
    }
}
