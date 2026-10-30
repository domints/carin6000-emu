// OS-9 Advanced Module Analysis Exporter for LLMs
// @category OS9
// @author CARiN_RE

import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.CodeUnitIterator;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.database.SpecExtension;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;

public class ExportOS9Modules extends GhidraScript {

    @Override
    public void run() throws Exception {
        // Output directory is the first script argument (see export_os9_modules.py).
        String[] args = getScriptArgs();
        File outputDir = new File(args.length > 0 ? args[0] : "os9_ghidra_exports");
        if (!outputDir.exists()) {
            outputDir.mkdirs();
        }

        String progName = currentProgram.getName();
        File outFile = new File(outputDir, progName + "_analysis.md");
        
        println("[*] Processing OS-9 Module: " + progName);

        // 1. The OS-9 module header (0x4AFC)
        int syncBytes = getShort(toAddr(0x00)) & 0xFFFF;
        
        if (syncBytes == 0x4AFC) {
            // M$Exec (0x30): entry point; M$Name (0x0C): offset of the module name.
            int entryOffset = getInt(toAddr(0x30));
            int nameOffset = getInt(toAddr(0x0C));

            Address entryAddr = toAddr(entryOffset);
            String modRealName = progName;

            try {
                // Read the module name from its ASCII bytes, safely
                StringBuilder nameBuilder = new StringBuilder();
                Address currentNameAddr = toAddr(nameOffset);
                for (int i = 0; i < 32; i++) {
                    byte b = getByte(currentNameAddr.add(i));
                    if (b == 0 || b == 0x0D || (b & 0xFF) > 127) {
                        if ((b & 0x7F) >= 32) { // OS-9 sometimes sets bit 7 on the last character
                            nameBuilder.append((char)(b & 0x7F));
                        }
                        break;
                    }
                    if (b >= 32 && b <= 126) {
                        nameBuilder.append((char)b);
                    }
                }
                if (nameBuilder.length() > 0) {
                    modRealName = nameBuilder.toString();
                }
            } catch (Exception e) {
                modRealName = progName;
            }

            println("    [+] Found OS-9 Header! Real Name: " + modRealName + " | Entry Offset: " + entryAddr);

            // Force a function at the real entry point, past the header
            disassemble(entryAddr);
            createFunction(entryAddr, "os9_" + modRealName.replaceAll("[^a-zA-Z0-9_]", "_") + "_main");
        } else {
            println("    [!] Warning: 0x4AFC sync pattern not found at offset 0. Running standard analysis.");
        }

        // 1b. Functions Ghidra cannot reach: calls go through the A6 jump table (jsr (d16,A6)), so
        // every "link a5,#n" (0x4E55, Microware C prologue) at an even address starts a function.
        {
            Address start = currentProgram.getMinAddress();
            Address end = currentProgram.getMaxAddress();
            int created = 0;
            for (Address a = start; a.compareTo(end) < 0; a = a.add(2)) {
                try {
                    if ((getShort(a) & 0xFFFF) != 0x4E55)
                        continue;
                } catch (Exception e) {
                    break;
                }
                if (getFunctionAt(a) != null || getInstructionContaining(a) != null && !getInstructionContaining(a).getAddress().equals(a))
                    continue;
                disassemble(a);
                if (createFunction(a, null) != null)
                    created++;
            }
            println("    [+] Functions created from link a5 prologues: " + created);
        }

        // 1c. Microware C calling convention: the first two arguments in D0 and D1, the rest on the
        // stack, result in D0; D2-D7/A2-A6 preserved (A6 is the process data pointer). Ghidra's
        // default 68k prototype passes everything on the stack, which loses the arguments.
        try {
            String proto =
                "<prototype name=\"microware\" extrapop=\"4\" stackshift=\"4\">" +
                "<input>" +
                "<pentry minsize=\"1\" maxsize=\"4\"><register name=\"D0\"/></pentry>" +
                "<pentry minsize=\"1\" maxsize=\"4\"><register name=\"D1\"/></pentry>" +
                "<pentry minsize=\"1\" maxsize=\"500\" align=\"4\"><addr offset=\"4\" space=\"stack\"/></pentry>" +
                "</input>" +
                "<output><pentry minsize=\"1\" maxsize=\"4\"><register name=\"D0\"/></pentry></output>" +
                "<unaffected>" +
                "<register name=\"D2\"/><register name=\"D3\"/><register name=\"D4\"/><register name=\"D5\"/>" +
                "<register name=\"D6\"/><register name=\"D7\"/><register name=\"A2\"/><register name=\"A3\"/>" +
                "<register name=\"A4\"/><register name=\"A5\"/><register name=\"A6\"/><register name=\"SP\"/>" +
                "</unaffected>" +
                "<killedbycall><register name=\"D0\"/><register name=\"D1\"/><register name=\"A0\"/><register name=\"A1\"/></killedbycall>" +
                "</prototype>";
            new SpecExtension(currentProgram).addReplaceCompilerSpecExtension(proto, monitor);
            FunctionIterator all = currentProgram.getFunctionManager().getFunctions(true);
            int set = 0;
            while (all.hasNext()) {
                all.next().setCallingConvention("microware");
                set++;
            }
            println("    [+] Microware calling convention set on " + set + " functions");
        } catch (Exception e) {
            println("    [!] Could not add the Microware calling convention: " + e);
        }

        // 2. Set up the decompiler
        DecompInterface decomp = new DecompInterface();
        decomp.toggleCCode(true);
        decomp.toggleSyntaxTree(true);
        decomp.openProgram(currentProgram);

        try (PrintWriter writer = new PrintWriter(new FileWriter(outFile))) {
            writer.println("# OS-9 Module Analysis: " + progName + "\n");
            writer.println("## Metadata");
            writer.println("- **Image Base:** " + currentProgram.getImageBase());
            writer.println("- **Min Address:** " + currentProgram.getMinAddress());
            writer.println("- **Max Address:** " + currentProgram.getMaxAddress());
            writer.println("\n---\n");

            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            int funcCount = 0;

            while (functions.hasNext()) {
                Function func = functions.next();
                funcCount++;
                
                writer.println("## Function: " + func.getName());
                writer.println("- **EntryPoint:** " + func.getEntryPoint() + "\n");

                // Decompiled C
                writer.println("### Decompiled C\n```c");
                DecompileResults result = decomp.decompileFunction(func, 60, monitor);
                if (result != null && result.decompileCompleted()) {
                    String cCode = result.getDecompiledFunction().getC();
                    if (cCode != null && !cCode.trim().isEmpty()) {
                        writer.println(cCode);
                    } else {
                        writer.println("// Decompilation output empty.");
                    }
                } else {
                    String errMsg = (result != null) ? result.getErrorMessage() : "Unknown error";
                    writer.println("// Decompilation incomplete/failed: " + errMsg);
                }
                writer.println("```\n");

                // Assembly Code
                writer.println("### Assembly\n```assembly");
                AddressSetView body = func.getBody();
                CodeUnitIterator codeUnits = currentProgram.getListing().getCodeUnits(body, true);
                while (codeUnits.hasNext()) {
                    CodeUnit cu = codeUnits.next();
                    writer.println(cu.getAddress() + ":  " + cu.toString());
                }
                writer.println("```\n");
                writer.println("---\n");
            }

            if (funcCount == 0) {
                writer.println("> **Note:** No executable functions identified in this module (likely raw data or table file).\n");
            }
        }
        println("[+] Export complete -> Saved to: " + outFile.getAbsolutePath());
    }
}