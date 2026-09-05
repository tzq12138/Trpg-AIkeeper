using System;
using System.Globalization;
using System.Text.Json;
using System.Windows.Data;

namespace ApiTestTool.Converters;

/// <summary>
/// Formats a string as pretty-printed JSON.
/// </summary>
public class JsonPrettyConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is not string s || string.IsNullOrWhiteSpace(s)) return "";
        try
        {
            var doc = JsonDocument.Parse(s);
            return JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch
        {
            return s;
        }
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        => value?.ToString() ?? "";
}
